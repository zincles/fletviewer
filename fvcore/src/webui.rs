//! Optional server-rendered diagnostic WebUI.

use crate::{
    BooruOriginalFetchRequest, BooruPost, CoreError, EhPageFetchRequest, ErrorCode,
    OperationSnapshot, PixivPageFetchRequest, ProfileKey, control::ControlState,
};
use axum::{
    Form, Router,
    extract::{Query, State},
    http::{HeaderValue, StatusCode, header},
    response::{Html, IntoResponse, Redirect, Response},
    routing::{get, post},
};
use serde::Deserialize;
use std::fmt::Write;

const STYLE: &str = include_str!("webui.css");
const DASHBOARD_REFRESH_SECONDS: u64 = 5;
const OPERATIONS_REFRESH_SECONDS: u64 = 2;
const OPERATION_REFRESH_SECONDS: u64 = 1;

#[derive(Deserialize)]
#[serde(default)]
struct SearchQuery {
    provider: String,
    profile: String,
    tags: String,
    page: u64,
    limit: u32,
}

impl Default for SearchQuery {
    fn default() -> Self {
        Self {
            provider: "danbooru".to_owned(),
            profile: "default".to_owned(),
            tags: String::new(),
            page: 1,
            limit: 20,
        }
    }
}

#[derive(Deserialize)]
struct PostQuery {
    provider: String,
    profile: String,
    id: u64,
}

#[derive(Deserialize)]
struct FetchForm {
    provider: String,
    profile: String,
    post_id: u64,
}

#[derive(Deserialize)]
struct PixivQuery {
    profile: String,
    id: String,
}

#[derive(Deserialize)]
struct PixivProfileQuery {
    profile: String,
}

#[derive(Deserialize)]
struct PixivSearchQuery {
    profile: String,
    query: String,
    #[serde(default = "default_page_one")]
    page: u32,
}

#[derive(Deserialize)]
struct PixivRankingQuery {
    profile: String,
    #[serde(default = "default_pixiv_ranking_mode")]
    mode: String,
    #[serde(default)]
    date: String,
    #[serde(default = "default_page_one")]
    page: u32,
}

#[derive(Deserialize)]
struct PixivFollowingQuery {
    profile: String,
    #[serde(default = "default_pixiv_following_visibility")]
    visibility: crate::PixivFollowingVisibility,
    #[serde(default = "default_page_one")]
    page: u32,
}

#[derive(Deserialize)]
struct PixivFetchForm {
    profile: String,
    illust_id: String,
    page: u32,
}

#[derive(Deserialize)]
struct EhHomeQuery {
    profile: String,
    #[serde(default)]
    search: String,
    direction: Option<crate::EhPageDirection>,
    gid: Option<u64>,
}

#[derive(Deserialize)]
struct FavoriteSearchForm {
    provider: String,
    profile: String,
    name: String,
    query: String,
}

#[derive(Deserialize)]
struct FavoriteSearchDeleteForm {
    id: String,
    provider: String,
    profile: String,
    query: String,
}

#[derive(Deserialize)]
struct EhGalleryQuery {
    profile: String,
    gid: u64,
    token: String,
    #[serde(default)]
    page: u32,
}

#[derive(Deserialize)]
struct EhPageFetchForm {
    profile: String,
    gid: u64,
    token: String,
    page: u32,
}

#[derive(Deserialize)]
struct EhReaderQuery {
    profile: String,
    gid: u64,
    token: String,
    #[serde(default)]
    page: u32,
    operation: Option<String>,
}

#[derive(Deserialize)]
struct EhReaderJumpForm {
    profile: String,
    gid: u64,
    token: String,
    page: u32,
}

#[derive(Deserialize)]
struct EhArchiveForm {
    profile: String,
    gid: u64,
    token: String,
    variant: String,
}

#[derive(Deserialize)]
struct ArchiveTaskForm {
    id: String,
}

#[derive(Default, Deserialize)]
#[serde(default)]
struct LocalGalleryQuery {
    id: String,
    offset: u32,
}

#[derive(Deserialize)]
struct LocalGalleryDeleteForm {
    id: String,
    confirmation_token: Option<String>,
}

#[derive(Deserialize)]
struct LocalGalleryImportForm {
    id: String,
}

#[derive(Deserialize)]
struct OperationQuery {
    id: String,
}

#[derive(Deserialize)]
struct CancelForm {
    id: String,
}

#[derive(Deserialize)]
struct ProfileCookieForm {
    provider: String,
    profile: String,
    cookie: String,
}

#[derive(Deserialize)]
struct ProfileApiCredentialsForm {
    provider: String,
    profile: String,
    api_user: String,
    api_key: String,
}

#[derive(Default, Deserialize)]
#[serde(default)]
struct ConfigurationQuery {
    edit: Option<String>,
    provider: Option<String>,
    profile: Option<String>,
}

#[derive(Deserialize)]
struct LanAccessForm {
    allow_lan: Option<String>,
}

pub(crate) fn routes() -> Router<ControlState> {
    Router::new()
        .route("/", get(dashboard))
        .route("/ui/search", get(search))
        .route("/ui/post", get(post_detail))
        .route("/ui/fetch", post(start_fetch))
        .route("/ui/pixiv", get(pixiv_detail))
        .route("/ui/pixiv/search", get(pixiv_search))
        .route("/ui/pixiv/ranking", get(pixiv_ranking))
        .route("/ui/pixiv/recommendations", get(pixiv_recommendations))
        .route("/ui/pixiv/following", get(pixiv_following))
        .route("/ui/pixiv/fetch", post(start_pixiv_fetch))
        .route("/ui/eh", get(eh_home))
        .route("/ui/favorite-search", post(create_favorite_search))
        .route("/ui/favorite-search/delete", post(delete_favorite_search))
        .route("/ui/eh/gallery", get(eh_gallery))
        .route("/ui/eh/fetch", post(start_eh_page_fetch))
        .route("/ui/eh/reader", get(eh_reader))
        .route("/ui/eh/reader/fetch", post(start_eh_reader_fetch))
        .route("/ui/eh/reader/jump", post(jump_eh_reader))
        .route("/ui/eh/archive", post(start_eh_archive))
        .route("/ui/archive-tasks", get(archive_tasks))
        .route("/ui/local-galleries", get(local_galleries))
        .route("/ui/local-data", get(local_data))
        .route("/ui/local-data/import", post(import_local_gallery))
        .route("/ui/config", get(configuration))
        .route("/ui/cache", get(image_cache))
        .route("/ui/cache/maintain", post(maintain_image_cache))
        .route("/ui/config/cookie", post(update_profile_cookie))
        .route(
            "/ui/config/api-credentials",
            post(update_profile_api_credentials),
        )
        .route("/ui/config/lan", post(update_lan_access))
        .route("/ui/local-gallery", get(local_gallery))
        .route("/ui/local-gallery/delete", post(local_gallery_delete))
        .route("/ui/archive-task/cancel", post(cancel_archive))
        .route("/ui/archive-task/retry", post(retry_archive))
        .route("/ui/operations", get(operations))
        .route("/ui/operation", get(operation))
        .route("/ui/cancel", post(cancel_operation))
}

async fn dashboard(State(state): State<ControlState>) -> Response {
    let snapshot = match state.core.snapshot().await {
        Ok(snapshot) => snapshot,
        Err(error) => return error_page(&error),
    };
    let operations = match state.core.operations().await {
        Ok(operations) => operations,
        Err(error) => return error_page(&error),
    };
    let mut profile_rows = String::new();
    let mut search_profile = None;
    for profile in &snapshot.profiles {
        let provider_profile = if matches!(profile.key.provider.as_str(), "danbooru" | "gelbooru") {
            search_profile.get_or_insert_with(|| profile.key.clone());
            let query = search_url(&profile.key.provider, &profile.key.profile, "", 1, 20);
            format!(
                "<a href=\"{}\">{} ({})</a>",
                escape(&query),
                provider_name(&profile.key.provider),
                escape(&profile.key.to_string())
            )
        } else if profile.key.provider == "eh" {
            format!(
                "<a href=\"{}\">{} ({})</a>",
                escape(&eh_home_url(&profile.key.profile, "", None)),
                provider_name(&profile.key.provider),
                escape(&profile.key.to_string())
            )
        } else {
            format!(
                "{} ({})",
                provider_name(&profile.key.provider),
                escape(&profile.key.to_string())
            )
        };
        let _ = write!(
            profile_rows,
            "<tr><td>{provider_profile}</td><td>{}</td><td>{}</td><td><code>{}</code></td><td>{} / {}</td><td>{} ms</td><td>{} / {}</td><td>{} / {}</td></tr>",
            provider_capability(&profile.key.provider),
            profile.generation,
            escape(&profile.base_url),
            yes_no(profile.has_cookie),
            yes_no(profile.has_api_credentials),
            profile.min_request_interval_ms,
            profile.active_requests,
            profile.max_concurrent_requests,
            profile.queued_requests,
            profile.max_concurrent_requests,
        );
    }
    if profile_rows.is_empty() {
        profile_rows
            .push_str("<tr><td colspan=\"8\" class=\"muted\">尚未配置 Provider 会话。</td></tr>");
    }
    let mut operation_rows = String::new();
    for operation in operations.iter().rev().take(20) {
        let result = operation
            .resource
            .as_ref()
            .map_or_else(String::new, |resource| {
                format!(
                    "<a href=\"/api/v1/resources/images/{}/{}\">{} 字节</a>",
                    resource.content_md5,
                    escape(&resource.extension),
                    resource.byte_length,
                )
            });
        let error = operation.error.as_ref().map_or_else(String::new, |error| {
            format!("{}: {}", error.code, escape(&error.message))
        });
        let _ = write!(
            operation_rows,
            "<tr><td><a href=\"{}\"><code>{}</code></a></td><td>{:?}</td><td>{:?}</td><td>{}</td><td>{}{}</td><td>{:?}</td><td>{}</td><td>{}</td></tr>",
            escape(&operation_url(operation.id)),
            operation.id,
            operation.kind,
            operation.state,
            escape(&operation.phase),
            operation.bytes_done,
            operation
                .bytes_total
                .map_or_else(String::new, |total| format!(" / {total}")),
            operation.source,
            if error.is_empty() { result } else { error },
            operation.revision,
        );
    }
    if operation_rows.is_empty() {
        operation_rows.push_str("<tr><td colspan=\"8\" class=\"muted\">尚未启动操作。</td></tr>");
    }
    let search = if let Some(profile) = search_profile {
        search_form(&SearchQuery {
            provider: profile.provider,
            profile: profile.profile,
            ..SearchQuery::default()
        })
    } else {
        "<p class=\"muted\">请先配置 Danbooru 或 Gelbooru 会话以启用搜索。</p>".to_owned()
    };
    let pixiv_profile = snapshot
        .profiles
        .iter()
        .find(|profile| profile.key.provider == "pixiv")
        .map(|profile| profile.key.profile.as_str())
        .unwrap_or("default");
    let pixiv_form = format!(
        "<form method=\"get\" action=\"/ui/pixiv\"><label>会话名称<input name=\"profile\" value=\"{}\" required></label><label>作品 ID<input name=\"id\" inputmode=\"numeric\" required></label><button type=\"submit\">查看作品详情</button></form><form method=\"get\" action=\"/ui/pixiv/search\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"page\" value=\"1\"><label>Pixiv 标签<input name=\"query\" required maxlength=\"500\"></label><button type=\"submit\">搜索 Pixiv</button></form><p><a href=\"{}\">浏览 Pixiv 推荐</a> · <a href=\"{}\">浏览 Pixiv 关注</a> · <a href=\"{}\">浏览 Pixiv 日榜</a></p>",
        escape(pixiv_profile),
        escape(pixiv_profile),
        escape(&pixiv_recommendations_url(pixiv_profile)),
        escape(&pixiv_following_url(
            pixiv_profile,
            crate::PixivFollowingVisibility::Public,
            1,
        )),
        escape(&pixiv_ranking_url(pixiv_profile, "day", "", 1)),
    );
    let eh_profile = snapshot
        .profiles
        .iter()
        .find(|profile| profile.key.provider == "eh")
        .map(|profile| profile.key.profile.as_str())
        .unwrap_or("default");
    let eh_form = format!(
        "<form method=\"get\" action=\"/ui/eh\"><label>会话名称<input name=\"profile\" value=\"{}\" required></label><button type=\"submit\">浏览 EH 主页</button></form>",
        escape(eh_profile),
    );
    let control = snapshot
        .control_listen
        .as_deref()
        .map_or_else(|| "已禁用".to_owned(), escape);
    let body = format!(
        concat!(
            "<h1>fvcore 调试面板</h1>",
            "<p class=\"muted\">所有可安全展示的运行状态均汇总在此。服务端渲染，无 Node.js 或外部资源。</p>",
            "<div class=\"grid\"><section class=\"card\"><h2>运行状态</h2><dl>",
            "<dt>实例名称</dt><dd>{}</dd><dt>Runtime ID</dt><dd><code>{}</code></dd>",
            "<dt>状态</dt><dd>{:?}</dd><dt>修订号</dt><dd>{}</dd><dt>运行时间</dt><dd>{} 秒</dd>",
            "<dt>排队命令</dt><dd>{}</dd><dt>最新事件</dt><dd>{}</dd></dl></section>",
            "<section class=\"card\"><h2>控制面</h2><dl><dt>HTTP</dt><dd>{}</dd>",
            "<dt>监听地址</dt><dd><code>{}</code></dd><dt>操作</dt><dd>{} 运行中 / {} 排队 / {} 保留</dd></dl></section>",
            "<section class=\"card wide\"><h2>存储</h2><table><tbody>",
            "<tr><th>Schema</th><td>{}</td><th>数据库</th><td>{} 字节</td></tr>",
            "<tr><th>数据</th><td colspan=\"3\"><code>{}</code></td></tr>",
            "<tr><th>缓存</th><td colspan=\"3\"><code>{}</code></td></tr>",
            "<tr><th>下载</th><td colspan=\"3\"><code>{}</code></td></tr>",
            "<tr><th>临时目录</th><td colspan=\"3\"><code>{}</code></td></tr></tbody></table></section>",
            "<section class=\"card wide\"><h2>Provider 会话</h2><table><thead><tr>",
            "<th>Provider/profile</th><th>当前能力</th><th>代次</th><th>基础 URL</th><th>Cookie / API 认证</th>",
            "<th>启动间隔</th><th>活动 / 上限</th><th>排队 / 上限</th></tr></thead>",
            "<tbody>{}</tbody></table></section>",
            "<section class=\"card wide\"><h2>Booru 搜索</h2>{}</section>",
            "<section class=\"card wide\"><h2>EH 主页</h2>{}</section>",
            "<section class=\"card wide\"><h2>Pixiv 作品</h2>{}</section>",
            "<section class=\"card wide\"><h2>最近操作</h2>",
            "<p class=\"muted\">最多显示最新 20 项操作。点击 ID 查看实时详情或取消。</p>",
            "<table><thead><tr><th>ID</th><th>类型</th><th>状态</th><th>阶段</th><th>字节</th>",
            "<th>来源</th><th>结果 / 错误</th><th>修订号</th></tr></thead>",
            "<tbody>{}</tbody></table></section></div>"
        ),
        escape(&snapshot.instance_name),
        snapshot.runtime_id,
        snapshot.state,
        snapshot.revision,
        snapshot.uptime_seconds,
        snapshot.queued_commands,
        snapshot.latest_event_sequence,
        yes_no(snapshot.control_enabled),
        control,
        snapshot.active_operations,
        snapshot.queued_operations,
        snapshot.retained_operations,
        snapshot.storage.schema_version,
        snapshot.storage.database_bytes,
        escape(&snapshot.storage.data),
        escape(&snapshot.storage.cache),
        escape(&snapshot.storage.downloads),
        escape(&snapshot.storage.temp),
        profile_rows,
        search,
        eh_form,
        pixiv_form,
        operation_rows,
    );
    html_page(
        StatusCode::OK,
        "调试面板",
        &body,
        Some(DASHBOARD_REFRESH_SECONDS),
    )
}

async fn eh_home(State(state): State<ControlState>, Query(query): Query<EhHomeQuery>) -> Response {
    let cursor = match (query.direction, query.gid) {
        (None, None) => None,
        (Some(direction), Some(gid)) => Some(crate::EhPageCursor { direction, gid }),
        _ => {
            return error_page(&CoreError::new(
                ErrorCode::InvalidInput,
                "EH 翻页方向和 GID 必须同时提供",
                false,
            ));
        }
    };
    let page = match state
        .core
        .eh_search(
            &ProfileKey::new("eh", &query.profile),
            &query.search,
            cursor,
        )
        .await
    {
        Ok(page) => page,
        Err(error) => return error_page(&error),
    };
    let mut galleries = String::new();
    for gallery in &page.galleries {
        let metadata = [
            gallery.category.as_deref(),
            gallery.language.as_deref(),
            gallery.published.as_deref(),
        ]
        .into_iter()
        .flatten()
        .map(escape)
        .collect::<Vec<_>>()
        .join(" · ");
        let pages = gallery
            .page_count
            .map_or_else(|| "页数未知".to_owned(), |value| format!("{value} 页"));
        let rating = gallery
            .rating
            .map_or_else(|| "评分未知".to_owned(), |value| format!("{value:.1} 星"));
        let uploader = escape(gallery.uploader.as_deref().unwrap_or("上传者未知"));
        let tags = escape(
            &gallery
                .tags
                .iter()
                .take(12)
                .cloned()
                .collect::<Vec<_>>()
                .join(" "),
        );
        let _ = write!(
            galleries,
            "<article class=\"card\"><p class=\"muted\">{}</p><h2><a href=\"{}\">{}</a></h2><p>GID {} · {} · {} · {}</p><p class=\"muted\">{}</p></article>",
            metadata,
            escape(&eh_gallery_url(
                &query.profile,
                gallery.gallery.gid,
                &gallery.gallery.token,
                0,
            )),
            escape(&gallery.title),
            gallery.gallery.gid,
            pages,
            rating,
            uploader,
            tags,
        );
    }
    if galleries.is_empty() {
        galleries.push_str("<p class=\"muted\">EH 主页没有返回可识别的 Gallery。</p>");
    }
    let mut paging = String::new();
    if let Some(previous) = page.previous {
        let _ = write!(
            paging,
            "<a href=\"{}\">上一页</a> ",
            escape(&eh_home_url(&query.profile, &query.search, Some(previous)))
        );
    }
    if let Some(next) = page.next {
        let _ = write!(
            paging,
            "<a href=\"{}\">下一页</a>",
            escape(&eh_home_url(&query.profile, &query.search, Some(next)))
        );
    }
    let favorites = match state.core.favorite_searches() {
        Ok(favorites) => favorites,
        Err(error) => return error_page(&error),
    };
    let mut favorite_links = String::new();
    for favorite in favorites
        .iter()
        .filter(|favorite| favorite.provider == "eh")
    {
        let _ = write!(
            favorite_links,
            "<li><a href=\"{}\">{}</a><form class=\"inline-form\" method=\"post\" action=\"/ui/favorite-search/delete\"><input type=\"hidden\" name=\"id\" value=\"{}\"><input type=\"hidden\" name=\"provider\" value=\"eh\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"query\" value=\"{}\"><button type=\"submit\">删除</button></form></li>",
            escape(&eh_home_url(&favorite.profile, &favorite.query, None)),
            escape(&favorite.name),
            favorite.id,
            escape(&favorite.profile),
            escape(&favorite.query),
        );
    }
    if favorite_links.is_empty() {
        favorite_links.push_str("<li class=\"muted\">尚无 EH 收藏搜索。</li>");
    }
    let save = if query.search.trim().is_empty() {
        String::new()
    } else {
        format!(
            "<form method=\"post\" action=\"/ui/favorite-search\"><input type=\"hidden\" name=\"provider\" value=\"eh\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"query\" value=\"{}\"><label>收藏名称<input name=\"name\" value=\"{}\" required maxlength=\"120\"></label><button type=\"submit\">收藏当前搜索</button></form>",
            escape(&query.profile),
            escape(&query.search),
            escape(&query.search)
        )
    };
    html_page(
        StatusCode::OK,
        "EH 主页",
        &format!(
            "<h1>EH 搜索</h1><form method=\"get\" action=\"/ui/eh\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><label>EH 查询<input name=\"search\" value=\"{}\" maxlength=\"2000\"></label><button type=\"submit\">搜索</button></form>{save}<section class=\"card\"><h2>收藏搜索</h2><ul>{favorite_links}</ul></section><p>会话 <code>eh/{}</code> · 代次 {} · {} 个 Gallery</p><p>{paging}</p><div class=\"grid gallery-grid\">{galleries}</div><p>{paging}</p>",
            escape(&query.profile),
            escape(&query.search),
            escape(&query.profile),
            page.generation,
            page.galleries.len(),
        ),
        None,
    )
}

async fn create_favorite_search(
    State(state): State<ControlState>,
    Form(form): Form<FavoriteSearchForm>,
) -> Response {
    match state.core.create_favorite_search(
        form.provider.clone(),
        form.profile.clone(),
        form.name,
        form.query.clone(),
    ) {
        Ok(_) => Redirect::to(&favorite_search_url(
            &form.provider,
            &form.profile,
            &form.query,
        ))
        .into_response(),
        Err(error) => error_page(&error),
    }
}

async fn delete_favorite_search(
    State(state): State<ControlState>,
    Form(form): Form<FavoriteSearchDeleteForm>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&form.id) {
        Ok(id) => id,
        Err(_) => {
            return error_page(&CoreError::new(
                ErrorCode::InvalidInput,
                "收藏搜索 ID 无效",
                false,
            ));
        }
    };
    match state.core.delete_favorite_search(id) {
        Ok(_) => Redirect::to(&favorite_search_url(
            &form.provider,
            &form.profile,
            &form.query,
        ))
        .into_response(),
        Err(error) => error_page(&error),
    }
}

async fn eh_gallery(
    State(state): State<ControlState>,
    Query(query): Query<EhGalleryQuery>,
) -> Response {
    let key = ProfileKey::new("eh", &query.profile);
    let gallery = crate::EhGalleryRef {
        gid: query.gid,
        token: query.token.clone(),
    };
    let detail = match state.core.eh_gallery_detail(&key, gallery.clone()).await {
        Ok(detail) => detail,
        Err(error) => return error_page(&error),
    };
    let thumbnails = match state.core.eh_thumbnails(&key, gallery, query.page).await {
        Ok(page) => page,
        Err(error) => return error_page(&error),
    };
    let tags = detail
        .tags
        .iter()
        .map(|(namespace, values)| format!("{}: {}", escape(namespace), escape(&values.join(", "))))
        .collect::<Vec<_>>()
        .join("<br>");
    let mut items = String::new();
    for item in &thumbnails.items {
        let _ = write!(
            items,
            "<article class=\"card\"><h2>第 {} 页 · {} x {}</h2><p><a href=\"{}\">进入阅读器</a> · <a href=\"{}\" rel=\"noreferrer\">打开 EH 图片页</a></p><code>{}</code><p class=\"muted\">阅读器图片可能经过重采样，不等同于 Original Archive 内的原始文件。</p></article>",
            item.page + 1,
            optional_number(item.width),
            optional_number(item.height),
            escape(&eh_reader_url(
                &query.profile,
                query.gid,
                &query.token,
                item.page,
                None,
            )),
            escape(item.page_url.as_str()),
            escape(&item.image_url),
        );
    }
    let next = thumbnails.next_page.map_or_else(String::new, |page| {
        format!(
            "<a href=\"{}\">下一页</a>",
            escape(&eh_gallery_url(
                &query.profile,
                query.gid,
                &query.token,
                page,
            ))
        )
    });
    html_page(
        StatusCode::OK,
        &detail.title,
        &format!(
            "<h1>{}</h1><p>{}</p><table><tr><th>GID</th><td>{}</td></tr><tr><th>上传者</th><td>{}</td></tr><tr><th>页数</th><td>{}</td></tr><tr><th>评分</th><td>{:.2} / {} 人</td></tr><tr><th>上传时间</th><td>{}</td></tr><tr><th>文件大小</th><td>{}</td></tr><tr><th>标签</th><td>{tags}</td></tr></table><h2>Archive 下载</h2><p class=\"error\">提交 Archive 可能消耗 GP。提交后中断不会自动重试，以避免重复扣费。</p><form method=\"post\" action=\"/ui/eh/archive\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"gid\" value=\"{}\"><input type=\"hidden\" name=\"token\" value=\"{}\"><label>类型<select name=\"variant\"><option value=\"resample\">Resample</option><option value=\"original\">Original</option></select></label><button type=\"submit\">确认提交并下载</button></form><h2>缩略图第 {} 页</h2><p>{next}</p><div class=\"grid gallery-grid\">{items}</div><p>{next}</p>",
            escape(&detail.title),
            escape(detail.subtitle.as_deref().unwrap_or("")),
            detail.gallery.gid,
            escape(detail.uploader.as_deref().unwrap_or("未知")),
            detail.page_count,
            detail.rating.unwrap_or(0.0),
            detail.rating_count,
            escape(detail.posted.as_deref().unwrap_or("未知")),
            escape(detail.file_size.as_deref().unwrap_or("未知")),
            escape(&query.profile),
            query.gid,
            escape(&query.token),
            thumbnails.page + 1,
        ),
        None,
    )
}

async fn eh_reader(
    State(state): State<ControlState>,
    Query(query): Query<EhReaderQuery>,
) -> Response {
    let operation = if let Some(id) = query.operation.as_deref() {
        let id = match id.parse() {
            Ok(id) => id,
            Err(_) => {
                return error_page(&CoreError::new(
                    ErrorCode::InvalidInput,
                    "阅读器 operation ID 必须是有效 UUID",
                    false,
                ));
            }
        };
        let operation = match state.core.operation(id).await {
            Ok(operation) => operation,
            Err(error) => return error_page(&error),
        };
        let expected_media = format!("{}:{}", query.gid, query.token);
        if !operation.resource_key.as_ref().is_some_and(|key| {
            key.provider == "eh"
                && key.media == expected_media
                && key.page == query.page
                && key.variant == "viewer"
        }) {
            return error_page(&CoreError::new(
                ErrorCode::InvalidInput,
                "operation 不属于当前 EH Gallery 阅读页",
                false,
            ));
        }
        if !operation.state.is_terminal() {
            let gallery_url = eh_gallery_url(&query.profile, query.gid, &query.token, 0);
            return html_page(
                StatusCode::OK,
                &format!("EH 阅读器 · 第 {} 页", query.page + 1),
                &format!(
                    "<header class=\"reader-header\"><div><p><a href=\"{}\">返回 Gallery</a></p><h1>EH 阅读器</h1><p>第 {} 页</p></div></header><section class=\"reader-status card\"><h2>正在获取阅读页图片</h2><p>{:?} · {} · {}{}</p><p><a href=\"{}\">查看 operation</a></p></section>",
                    escape(&gallery_url),
                    query.page + 1,
                    operation.state,
                    escape(&operation.phase),
                    operation.bytes_done,
                    operation
                        .bytes_total
                        .map_or_else(String::new, |total| format!(" / {total}")),
                    escape(&operation_url(operation.id)),
                ),
                Some(OPERATION_REFRESH_SECONDS),
            );
        }
        Some(operation)
    } else {
        None
    };
    let key = ProfileKey::new("eh", &query.profile);
    let gallery = crate::EhGalleryRef {
        gid: query.gid,
        token: query.token.clone(),
    };
    let detail = match state.core.eh_gallery_detail(&key, gallery).await {
        Ok(detail) => detail,
        Err(error) => return error_page(&error),
    };
    if query.page >= detail.page_count {
        return error_page(&CoreError::new(
            ErrorCode::InvalidInput,
            format!("阅读页必须小于画廊总页数 {}", detail.page_count),
            false,
        ));
    }

    let previous = (query.page > 0).then(|| {
        eh_reader_url(
            &query.profile,
            query.gid,
            &query.token,
            query.page - 1,
            None,
        )
    });
    let next = (query.page + 1 < detail.page_count).then(|| {
        eh_reader_url(
            &query.profile,
            query.gid,
            &query.token,
            query.page + 1,
            None,
        )
    });
    let navigation = reader_navigation(previous.as_deref(), next.as_deref());
    let content = if let Some(operation) = operation {
        if let Some(resource) = operation.resource {
            let resource_url = format!(
                "/api/v1/resources/images/{}/{}",
                resource.content_md5, resource.extension
            );
            format!(
                "<figure class=\"reader-image\"><img src=\"{}\" alt=\"{} 第 {} 页阅读器图片\"><figcaption>{} · {} 字节 · {:?}</figcaption></figure>",
                escape(&resource_url),
                escape(&detail.title),
                query.page + 1,
                escape(&resource.mime_type),
                resource.byte_length,
                resource.source,
            )
        } else {
            let error = operation.error.map_or_else(
                || "操作结束但没有返回图片资源".to_owned(),
                |error| format!("{}: {}", error.code, error.message),
            );
            format!(
                "<p class=\"error\">{}</p>{}",
                escape(&error),
                eh_reader_fetch_form(&query),
            )
        }
    } else {
        eh_reader_fetch_form(&query)
    };
    let gallery_url = eh_gallery_url(&query.profile, query.gid, &query.token, 0);
    html_page(
        StatusCode::OK,
        &format!("{} · 第 {} 页", detail.title, query.page + 1),
        &format!(
            "<header class=\"reader-header\"><div><p><a href=\"{}\">返回 Gallery</a></p><h1>{}</h1><p>第 {} / {} 页</p></div>{navigation}</header><form class=\"reader-jump\" method=\"post\" action=\"/ui/eh/reader/jump\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"gid\" value=\"{}\"><input type=\"hidden\" name=\"token\" value=\"{}\"><label>跳转到页<input name=\"page\" type=\"number\" min=\"1\" max=\"{}\" value=\"{}\" required></label><button type=\"submit\">跳转</button></form><p class=\"muted\">网页阅读器图片可能经过重采样；只有 Original Archive 明确承诺归档原始文件。上一页/下一页可使用浏览器 access key。</p>{content}<footer class=\"reader-footer\">{navigation}</footer>",
            escape(&gallery_url),
            escape(&detail.title),
            query.page + 1,
            detail.page_count,
            escape(&query.profile),
            query.gid,
            escape(&query.token),
            detail.page_count,
            query.page + 1,
        ),
        None,
    )
}

async fn start_eh_archive(
    State(state): State<ControlState>,
    Form(form): Form<EhArchiveForm>,
) -> Response {
    let variant = match form.variant.as_str() {
        "original" => crate::EhArchiveVariant::Original,
        "resample" => crate::EhArchiveVariant::Resample,
        _ => {
            return error_page(&CoreError::new(
                ErrorCode::InvalidInput,
                "Archive 类型无效",
                false,
            ));
        }
    };
    match state
        .core
        .start_eh_archive_download(crate::EhArchiveDownloadRequest {
            profile: ProfileKey::new("eh", form.profile),
            gallery: crate::EhGalleryRef {
                gid: form.gid,
                token: form.token,
            },
            variant,
        })
        .await
    {
        Ok(_) => Redirect::to("/ui/archive-tasks").into_response(),
        Err(error) => error_page(&error),
    }
}

async fn archive_tasks(State(state): State<ControlState>) -> Response {
    let tasks = state.core.archive_tasks().await;
    let active = tasks.iter().any(|task| !task.state.is_terminal());
    let mut rows = String::new();
    for task in tasks.iter().rev() {
        let action = if !task.state.is_terminal() {
            format!(
                "<form method=\"post\" action=\"/ui/archive-task/cancel\"><input type=\"hidden\" name=\"id\" value=\"{}\"><button type=\"submit\">取消</button></form>",
                task.id
            )
        } else if matches!(
            task.state,
            crate::ArchiveTaskState::Failed | crate::ArchiveTaskState::Cancelled
        ) {
            format!(
                "<form method=\"post\" action=\"/ui/archive-task/retry\"><input type=\"hidden\" name=\"id\" value=\"{}\"><button type=\"submit\">仅重试下载</button></form>",
                task.id
            )
        } else {
            String::new()
        };
        let _ = write!(
            rows,
            "<tr><td><code>{}</code></td><td>{:?}</td><td>{} / {}</td><td>{:?}</td><td>{}</td><td>{}</td></tr>",
            task.id,
            task.state,
            task.bytes_done,
            task.bytes_total
                .map_or_else(|| "?".to_owned(), |value| value.to_string()),
            task.variant,
            escape(task.error.as_deref().unwrap_or("")),
            action
        );
    }
    if rows.is_empty() {
        rows.push_str("<tr><td colspan=\"6\" class=\"muted\">暂无 Archive 任务。</td></tr>");
    }
    html_page(
        StatusCode::OK,
        "Archive 任务",
        &format!(
            "<h1>Archive 任务</h1><p class=\"muted\">cost_unknown 任务不会自动重放付费提交。</p><table><thead><tr><th>ID</th><th>状态</th><th>字节</th><th>类型</th><th>错误</th><th>操作</th></tr></thead><tbody>{rows}</tbody></table>"
        ),
        active.then_some(2),
    )
}

async fn local_galleries(State(state): State<ControlState>) -> Response {
    let galleries = match state.core.local_galleries().await {
        Ok(galleries) => galleries,
        Err(error) => return error_page(&error),
    };
    let mut cards = String::new();
    for gallery in &galleries {
        let cover = if gallery.cover_available {
            format!(
                "<img class=\"gallery-cover\" loading=\"lazy\" src=\"/api/v1/local-galleries/{}/cover\" alt=\"{} 封面\">",
                gallery.id,
                escape(&gallery.title),
            )
        } else {
            String::new()
        };
        let _ = write!(
            cards,
            "<article class=\"card\">{}<h2><a href=\"{}\">{}</a></h2><p>GID {} · {} 字节</p><p>{} · 封面 {} · ComicInfo {}</p></article>",
            cover,
            escape(&local_gallery_url(gallery.id, 0)),
            escape(&gallery.title),
            gallery.gid,
            gallery.archive_bytes,
            escape(&gallery.provider),
            yes_no(gallery.cover_available),
            yes_no(gallery.comic_info_available),
        );
    }
    if cards.is_empty() {
        cards.push_str("<p class=\"muted\">暂无已提交的本地画廊。</p>");
    }
    html_page(
        StatusCode::OK,
        "本地画廊",
        &format!("<h1>本地画廊</h1><div class=\"grid\">{cards}</div>"),
        None,
    )
}

async fn local_data(State(state): State<ControlState>) -> Response {
    let inventory = match state.core.local_gallery_inventory().await {
        Ok(inventory) => inventory,
        Err(error) => return error_page(&error),
    };
    let mut rows = String::new();
    for entry in &inventory.entries {
        let status = local_inventory_status(entry.status);
        let issues = if entry.issues.is_empty() {
            "-".to_owned()
        } else {
            entry
                .issues
                .iter()
                .map(|issue| {
                    format!(
                        "<code>{}</code>: {}",
                        escape(&issue.code),
                        escape(&issue.message)
                    )
                })
                .collect::<Vec<_>>()
                .join("<br>")
        };
        let action = if entry.status == crate::LocalGalleryInventoryStatus::UnregisteredImportable {
            entry.gallery_id.map_or_else(String::new, |id| {
                format!(
                    "<form method=\"post\" action=\"/ui/local-data/import\"><input type=\"hidden\" name=\"id\" value=\"{id}\"><button type=\"submit\">导入登记</button></form>"
                )
            })
        } else if entry.status == crate::LocalGalleryInventoryStatus::RegisteredHealthy {
            entry.gallery_id.map_or_else(String::new, |id| {
                format!("<a href=\"{}\">打开</a>", escape(&local_gallery_url(id, 0)))
            })
        } else {
            String::new()
        };
        let _ = write!(
            rows,
            "<tr><td>{}</td><td><code>{}</code></td><td>{}</td><td>{}</td><td>{} / {}</td><td>{}</td><td>{}</td></tr>",
            status,
            escape(&entry.directory_name),
            entry
                .gallery_id
                .map_or_else(|| "-".to_owned(), |id| format!("<code>{id}</code>")),
            escape(entry.title.as_deref().unwrap_or("-")),
            entry
                .page_count
                .map_or_else(|| "?".to_owned(), |value| value.to_string()),
            entry
                .archive_bytes
                .map_or_else(|| "?".to_owned(), |value| value.to_string()),
            issues,
            action,
        );
    }
    if rows.is_empty() {
        rows.push_str(
            "<tr><td colspan=\"7\" class=\"muted\">受管目录中没有本地画廊或异常条目。</td></tr>",
        );
    }
    html_page(
        StatusCode::OK,
        "本地数据管理",
        &format!(
            "<h1>本地数据管理</h1><p class=\"muted\">扫描仅覆盖受管 EHArchieve 根目录。导入只登记完整通过校验的候选，不移动或改写 ZIP、gallery.json 与 ComicInfo.xml。</p><div class=\"grid\"><section class=\"card\"><h2>已登记健康</h2><strong>{}</strong></section><section class=\"card\"><h2>已登记损坏</h2><strong>{}</strong></section><section class=\"card\"><h2>可导入</h2><strong>{}</strong></section><section class=\"card\"><h2>格式无效</h2><strong>{}</strong></section></div><p>扫描时间 {}</p><table><thead><tr><th>状态</th><th>目录名</th><th>Gallery ID</th><th>标题</th><th>页数 / ZIP 字节</th><th>问题</th><th>操作</th></tr></thead><tbody>{rows}</tbody></table>",
            inventory.registered_healthy,
            inventory.registered_damaged,
            inventory.unregistered_importable,
            inventory.invalid,
            inventory.scanned_at,
        ),
        None,
    )
}

async fn import_local_gallery(
    State(state): State<ControlState>,
    Form(form): Form<LocalGalleryImportForm>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&form.id) {
        Ok(id) => id,
        Err(_) => {
            return error_page(&CoreError::new(
                ErrorCode::InvalidInput,
                "本地画廊 ID 无效",
                false,
            ));
        }
    };
    match state.core.import_local_gallery(id).await {
        Ok(_) => Redirect::to("/ui/local-data").into_response(),
        Err(error) => error_page(&error),
    }
}

async fn configuration(
    State(state): State<ControlState>,
    Query(query): Query<ConfigurationQuery>,
) -> Response {
    let config = match state.core.effective_config().await {
        Ok(config) => config,
        Err(error) => return error_page(&error),
    };
    let mut profiles = String::new();
    let mut credential_settings = String::new();
    for profile in &config.profiles {
        let _ = write!(
            profiles,
            "<tr><td><code>{}/{}</code></td><td><code>{}</code></td><td><code>{}</code></td><td>{}</td><td>{} / {}</td><td>{} + {} / {}</td><td>{}</td><td>{} ms</td></tr>",
            escape(&profile.provider),
            escape(&profile.profile),
            escape(&profile.base_url),
            escape(&profile.user_agent),
            escape(&profile.allowed_redirect_hosts.join(", ")),
            escape(profile.cookie_env.as_deref().unwrap_or("未配置")),
            yes_no(profile.cookie_loaded),
            escape(profile.api_user_env.as_deref().unwrap_or("未配置")),
            escape(profile.api_key_env.as_deref().unwrap_or("未配置")),
            yes_no(profile.api_credentials_loaded),
            profile.max_concurrent_requests,
            profile.min_request_interval_ms,
        );
        let key = ProfileKey::new(&profile.provider, &profile.profile);
        let credentials = match state.core.dangerous_profile_credentials(&key) {
            Ok(credentials) => credentials,
            Err(error) => return error_page(&error),
        };
        let editing_cookie = editing(&query, "cookie", &profile.provider, &profile.profile);
        let editing_api = editing(
            &query,
            "api-credentials",
            &profile.provider,
            &profile.profile,
        );
        let cookie = credentials.cookie.as_deref().unwrap_or_default();
        let api_user = credentials.api_user.as_deref().unwrap_or_default();
        let api_key = credentials.api_key.as_deref().unwrap_or_default();
        let cookie_control = if editing_cookie {
            format!(
                "<form class=\"setting-editor\" method=\"post\" action=\"/ui/config/cookie\"><input type=\"hidden\" name=\"provider\" value=\"{}\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><label>Cookie<textarea name=\"cookie\" rows=\"4\" spellcheck=\"false\">{}</textarea></label><div class=\"setting-actions\"><button type=\"submit\">保存并重建 Session</button><a href=\"/ui/config\">取消</a></div><p class=\"muted\">空值保存会清除 Cookie。</p></form>",
                escape(&profile.provider),
                escape(&profile.profile),
                escape(cookie),
            )
        } else {
            setting_display(
                cookie,
                &config_edit_url("cookie", &profile.provider, &profile.profile),
            )
        };
        let api_control = if editing_api {
            format!(
                "<form class=\"setting-editor\" method=\"post\" action=\"/ui/config/api-credentials\"><input type=\"hidden\" name=\"provider\" value=\"{}\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><label>API user<input name=\"api_user\" value=\"{}\" autocomplete=\"off\" spellcheck=\"false\"></label><label>API key<input name=\"api_key\" value=\"{}\" autocomplete=\"off\" spellcheck=\"false\"></label><div class=\"setting-actions\"><button type=\"submit\">保存并重建 Session</button><a href=\"/ui/config\">取消</a></div><p class=\"muted\">两项必须同时填写；全部留空会清除 API credentials。</p></form>",
                escape(&profile.provider),
                escape(&profile.profile),
                escape(api_user),
                escape(api_key),
            )
        } else {
            setting_display(
                &format!("user: {api_user}\nkey: {api_key}"),
                &config_edit_url("api-credentials", &profile.provider, &profile.profile),
            )
        };
        let _ = write!(
            credential_settings,
            "<section class=\"card wide\"><h2><code>{}/{}</code> 明文凭据</h2><div class=\"setting-row\"><div><strong>Cookie</strong>{cookie_control}</div></div><div class=\"setting-row\"><div><strong>API credentials</strong>{api_control}</div></div></section>",
            escape(&profile.provider),
            escape(&profile.profile),
        );
    }
    let lan_control = if query.edit.as_deref() == Some("allow-lan") {
        format!(
            "<form class=\"setting-editor\" method=\"post\" action=\"/ui/config/lan\"><label><select name=\"allow_lan\"><option value=\"true\"{}>开启</option><option value=\"false\"{}>关闭</option></select></label><div class=\"setting-actions\"><button type=\"submit\">保存</button><a href=\"/ui/config\">取消</a></div></form>",
            if config.control.allow_lan {
                " selected"
            } else {
                ""
            },
            if config.control.allow_lan {
                ""
            } else {
                " selected"
            },
        )
    } else {
        setting_display(
            if config.control.allow_lan {
                "开启"
            } else {
                "关闭"
            },
            "/ui/config?edit=allow-lan",
        )
    };
    html_page(
        StatusCode::OK,
        "当前生效配置",
        &format!(
            "<h1>当前生效配置</h1><p class=\"error\"><strong>DANGER:</strong> 此调试面板没有认证。下方会明文显示 Cookie、API user 和 API key，并将修改明文写入 config.json。任何能访问此面板的人都能读取和修改这些凭据。</p><p class=\"muted\">JSON 配置 API 仍保持脱敏，不返回 secret 或代理 URL/凭据值。每次只编辑一个原子配置单元。</p><div class=\"grid\"><section class=\"card\"><h2>Runtime</h2><dl><dt>Schema</dt><dd>{}</dd><dt>实例</dt><dd>{}</dd><dt>命令容量</dt><dd>{}</dd><dt>关闭期限</dt><dd>{} 秒</dd></dl></section><section class=\"card\"><h2>HTTP</h2><dl><dt>启用</dt><dd>{}</dd><dt>配置监听</dt><dd><code>{}</code></dd><dt>局域网访问</dt><dd>{lan_control}<span class=\"muted\">保存后必须重启 fvcore 才会重新绑定监听地址。</span></dd><dt>WebUI</dt><dd>{}</dd></dl></section><section class=\"card\"><h2>网络</h2><dl><dt>连接 / 请求超时</dt><dd>{} / {} 秒</dd><dt>响应上限</dt><dd>{} 字节</dd><dt>重定向</dt><dd>{}</dd><dt>代理</dt><dd>{}</dd></dl></section><section class=\"card\"><h2>图片</h2><dl><dt>单图上限</dt><dd>{}</dd><dt>内存缓存</dt><dd>{}</dd><dt>在途字节</dt><dd>{}</dd><dt>写盘队列</dt><dd>{}</dd></dl></section><section class=\"card\"><h2>Operation</h2><dl><dt>活动上限</dt><dd>{}</dd><dt>排队上限</dt><dd>{}</dd><dt>终态保留</dt><dd>{}</dd><dt>默认期限</dt><dd>{} 秒</dd></dl></section><section class=\"card\"><h2>Event</h2><dl><dt>通道容量</dt><dd>{}</dd><dt>Journal 保留</dt><dd>{}</dd></dl></section><section class=\"card wide\"><h2>存储域</h2><table><tr><th>Schema</th><td>{}</td><th>数据库</th><td>{} 字节</td></tr><tr><th>Data</th><td colspan=\"3\"><code>{}</code></td></tr><tr><th>Cache</th><td colspan=\"3\"><code>{}</code></td></tr><tr><th>Downloads</th><td colspan=\"3\"><code>{}</code></td></tr><tr><th>Temp</th><td colspan=\"3\"><code>{}</code></td></tr></table></section><section class=\"card wide\"><h2>Provider 配置</h2><table><thead><tr><th>Profile</th><th>Origin</th><th>User-Agent</th><th>Redirect hosts</th><th>Cookie env / 已加载</th><th>API user + key env / 已加载</th><th>并发</th><th>间隔</th></tr></thead><tbody>{profiles}</tbody></table></section>{credential_settings}</div>",
            config.schema_version,
            escape(&config.instance_name),
            config.command_capacity,
            config.shutdown_seconds,
            yes_no(config.control.enabled),
            config.control.listen,
            yes_no(config.control.webui_enabled),
            config.network.connect_timeout_seconds,
            config.network.request_timeout_seconds,
            config.network.max_response_bytes,
            config.network.max_redirects,
            yes_no(config.network.proxy_configured),
            config.images.max_image_bytes,
            config.images.memory_cache_bytes,
            config.images.max_inflight_bytes,
            config.images.cache_write_queue,
            config.operations.max_active,
            config.operations.max_queued,
            config.operations.retained_terminal,
            config.operations.default_deadline_seconds,
            config.events.capacity,
            config.events.retained,
            config.storage.schema_version,
            config.storage.database_bytes,
            escape(&config.storage.data),
            escape(&config.storage.cache),
            escape(&config.storage.downloads),
            escape(&config.storage.temp),
        ),
        None,
    )
}

async fn image_cache(State(state): State<ControlState>) -> Response {
    let cache = match state.core.image_cache_snapshot().await {
        Ok(cache) => cache,
        Err(error) => return error_page(&error),
    };
    let providers = cache
        .semantic
        .by_provider
        .iter()
        .map(|(provider, count)| format!("{}: {}", escape(provider), count))
        .collect::<Vec<_>>()
        .join(" · ");
    let variants = cache
        .semantic
        .by_variant
        .iter()
        .map(|(variant, count)| format!("{}: {}", escape(variant), count))
        .collect::<Vec<_>>()
        .join(" · ");
    html_page(
        StatusCode::OK,
        "图片缓存",
        &format!(
            "<h1>图片缓存</h1><div class=\"grid\"><section class=\"card\"><h2>内存与网络</h2><dl><dt>内存</dt><dd>{} / {} 字节</dd><dt>内存条目</dt><dd>{}</dd><dt>在途</dt><dd>{} / {} 字节</dd><dt>共享传输</dt><dd>{}</dd></dl></section><section class=\"card\"><h2>磁盘与索引</h2><dl><dt>有效 blob</dt><dd>{}</dd><dt>有效字节</dt><dd>{}</dd><dt>无效 blob</dt><dd>{}</dd><dt>Alias</dt><dd>{}</dd><dt>Staging</dt><dd>{}</dd><dt>写盘队列</dt><dd>{} / {}</dd></dl></section><section class=\"card wide\"><h2>语义资源</h2><dl><dt>已缓存页</dt><dd>{}</dd><dt>媒体项</dt><dd>{}</dd><dt>语义资源</dt><dd>{}</dd><dt>Provider</dt><dd>{}</dd><dt>Variant</dt><dd>{}</dd></dl><p class=\"muted\">页数按唯一 provider/media/page 统计并排除 cover；同一页的 thumbnail、viewer 或 original 不重复计数。Blob 是唯一实际内容，语义资源可能共享同一 blob。</p></section></div><form method=\"post\" action=\"/ui/cache/maintain\"><button type=\"submit\">清理无效 blob、staging 与 stale alias</button></form><p class=\"muted\">维护只处理 fvcore 管理的图片缓存，不接受外部路径，也不会按年龄删除有效 blob。</p>",
            cache.memory_bytes,
            cache.memory_limit_bytes,
            cache.memory_entries,
            cache.inflight_bytes,
            cache.inflight_limit_bytes,
            cache.active_transfers,
            cache.disk_blob_count,
            cache.disk_bytes,
            cache.invalid_blob_count,
            cache.alias_count,
            cache.staging_file_count,
            cache.write_queue_depth,
            cache.write_queue_capacity,
            cache.semantic.page_count,
            cache.semantic.media_count,
            cache.semantic.resource_count,
            if providers.is_empty() {
                "-"
            } else {
                &providers
            },
            if variants.is_empty() { "-" } else { &variants },
        ),
        None,
    )
}

async fn maintain_image_cache(State(state): State<ControlState>) -> Response {
    match state.core.maintain_image_cache().await {
        Ok(_) => Redirect::to("/ui/cache").into_response(),
        Err(error) => error_page(&error),
    }
}

async fn update_lan_access(
    State(state): State<ControlState>,
    Form(form): Form<LanAccessForm>,
) -> Response {
    match state
        .core
        .set_allow_lan(form.allow_lan.as_deref() == Some("true"))
        .await
    {
        Ok(()) => Redirect::to("/ui/config").into_response(),
        Err(error) => error_page(&error),
    }
}

/// DANGER: Unauthenticated debug endpoint that persists and echoes plaintext credentials.
async fn update_profile_cookie(
    State(state): State<ControlState>,
    Form(form): Form<ProfileCookieForm>,
) -> Response {
    let optional = |value: String| (!value.trim().is_empty()).then_some(value);
    match state
        .core
        .update_profile_cookie(
            ProfileKey::new(form.provider, form.profile),
            optional(form.cookie),
        )
        .await
    {
        Ok(_) => Redirect::to("/ui/config").into_response(),
        Err(error) => error_page(&error),
    }
}

/// DANGER: Unauthenticated debug endpoint that persists a plaintext API credential pair.
async fn update_profile_api_credentials(
    State(state): State<ControlState>,
    Form(form): Form<ProfileApiCredentialsForm>,
) -> Response {
    let optional = |value: String| (!value.trim().is_empty()).then_some(value);
    match state
        .core
        .update_profile_api_credentials(
            ProfileKey::new(form.provider, form.profile),
            optional(form.api_user),
            optional(form.api_key),
        )
        .await
    {
        Ok(_) => Redirect::to("/ui/config").into_response(),
        Err(error) => error_page(&error),
    }
}

async fn local_gallery(
    State(state): State<ControlState>,
    Query(query): Query<LocalGalleryQuery>,
) -> Response {
    let id = match query.id.parse() {
        Ok(id) => id,
        Err(_) => {
            return error_page(&CoreError::new(
                ErrorCode::InvalidInput,
                "本地画廊 ID 无效",
                false,
            ));
        }
    };
    const LIMIT: u32 = 100;
    let detail = match state.core.local_gallery(id, query.offset, LIMIT).await {
        Ok(detail) => detail,
        Err(error) => return error_page(&error),
    };
    let cover = if detail.gallery.cover_available {
        format!(
            "<img class=\"detail-cover\" src=\"/api/v1/local-galleries/{}/cover\" alt=\"{} 封面\">",
            detail.gallery.id,
            escape(&detail.gallery.title),
        )
    } else {
        String::new()
    };
    let mut pages = String::new();
    for page in &detail.pages {
        let resource = format!(
            "/api/v1/local-galleries/{}/pages/{}",
            detail.gallery.id, page.id
        );
        let _ = write!(
            pages,
            "<article class=\"card local-page\"><a href=\"{}\"><img loading=\"lazy\" src=\"{}\" alt=\"第 {} 页\"></a><p>第 {} 页 · {} · {} 字节</p></article>",
            escape(&resource),
            escape(&resource),
            page.number,
            page.number,
            escape(&page.filename),
            page.byte_length,
        );
    }
    if pages.is_empty() {
        pages.push_str("<p class=\"muted\">该窗口没有可读取页面。</p>");
    }
    let mut paging = String::new();
    if detail.offset > 0 {
        let previous = detail.offset.saturating_sub(LIMIT);
        let _ = write!(
            paging,
            "<a href=\"{}\">上一批</a> ",
            escape(&local_gallery_url(id, previous))
        );
    }
    let next = detail.offset.saturating_add(detail.pages.len() as u32);
    if next < detail.total_pages {
        let _ = write!(
            paging,
            "<a href=\"{}\">下一批</a>",
            escape(&local_gallery_url(id, next))
        );
    }
    html_page(
        StatusCode::OK,
        &detail.gallery.title,
        &format!(
            "<h1>{}</h1>{}<p>EH GID {} · 共 {} 页 · 当前 {} - {}</p><p>{paging}</p><div class=\"grid local-pages\">{pages}</div><p>{paging}</p><h2>画廊管理</h2><p><a href=\"/api/v1/local-galleries/{}/export\">导出原始 ZIP</a></p><p class=\"muted\">Web 下载由 Core 流式发送，不暴露服务器存储路径。</p><p class=\"error\">删除会永久移除原始 ZIP、封面、gallery.json 和 ComicInfo.xml。</p><form method=\"post\" action=\"/ui/local-gallery/delete\"><input type=\"hidden\" name=\"id\" value=\"{}\"><button type=\"submit\">预览永久删除</button></form>",
            escape(&detail.gallery.title),
            cover,
            detail.gallery.gid,
            detail.total_pages,
            detail.offset.saturating_add(1),
            next,
            detail.gallery.id,
            detail.gallery.id,
        ),
        None,
    )
}

async fn local_gallery_delete(
    State(state): State<ControlState>,
    Form(form): Form<LocalGalleryDeleteForm>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&form.id) {
        Ok(id) => id,
        Err(_) => {
            return error_page(&CoreError::new(
                ErrorCode::InvalidInput,
                "本地画廊 ID 无效",
                false,
            ));
        }
    };
    if let Some(token) = form.confirmation_token {
        let confirmation_token = match uuid::Uuid::parse_str(&token) {
            Ok(token) => token,
            Err(_) => {
                return error_page(&CoreError::new(
                    ErrorCode::InvalidInput,
                    "删除确认令牌无效",
                    false,
                ));
            }
        };
        return match state
            .core
            .delete_local_gallery(id, crate::LocalGalleryDeleteRequest { confirmation_token })
            .await
        {
            Ok(result) => html_page(
                StatusCode::OK,
                "本地画廊已删除",
                &format!(
                    "<h1>本地画廊已永久删除</h1><p>已删除 {} 个文件，共 {} 字节。</p><p><a href=\"/ui/local-galleries\">返回本地画廊</a></p>",
                    result.deleted_files, result.deleted_bytes
                ),
                None,
            ),
            Err(error) => error_page(&error),
        };
    }
    match state.core.prepare_local_gallery_delete(id).await {
        Ok(confirmation) => html_page(
            StatusCode::OK,
            "确认删除本地画廊",
            &format!(
                "<h1>确认永久删除</h1><p class=\"error\">此操作不可撤销，将删除 {} 个文件，共 {} 字节。确认令牌将在 {} 失效，且画廊有任何变化都会拒绝删除。</p><form method=\"post\" action=\"/ui/local-gallery/delete\"><input type=\"hidden\" name=\"id\" value=\"{}\"><input type=\"hidden\" name=\"confirmation_token\" value=\"{}\"><button type=\"submit\">确认永久删除原始 ZIP 和画廊</button></form><p><a href=\"{}\">取消</a></p>",
                confirmation.file_count,
                confirmation.total_bytes,
                confirmation.expires_at,
                confirmation.gallery_id,
                confirmation.confirmation_token,
                escape(&local_gallery_url(confirmation.gallery_id, 0)),
            ),
            None,
        ),
        Err(error) => error_page(&error),
    }
}

async fn cancel_archive(
    State(state): State<ControlState>,
    Form(form): Form<ArchiveTaskForm>,
) -> Response {
    let Ok(id) = form.id.parse() else {
        return error_page(&CoreError::new(
            ErrorCode::InvalidInput,
            "Archive 任务 ID 无效",
            false,
        ));
    };
    match state.core.cancel_archive_task(id).await {
        Ok(_) => Redirect::to("/ui/archive-tasks").into_response(),
        Err(error) => error_page(&error),
    }
}

async fn retry_archive(
    State(state): State<ControlState>,
    Form(form): Form<ArchiveTaskForm>,
) -> Response {
    let Ok(id) = form.id.parse() else {
        return error_page(&CoreError::new(
            ErrorCode::InvalidInput,
            "Archive 任务 ID 无效",
            false,
        ));
    };
    match state.core.retry_archive_task(id).await {
        Ok(_) => Redirect::to("/ui/archive-tasks").into_response(),
        Err(error) => error_page(&error),
    }
}

async fn start_eh_page_fetch(
    State(state): State<ControlState>,
    Form(form): Form<EhPageFetchForm>,
) -> Response {
    match state
        .core
        .start_eh_page_fetch(EhPageFetchRequest {
            profile: ProfileKey::new("eh", form.profile),
            gallery: crate::EhGalleryRef {
                gid: form.gid,
                token: form.token,
            },
            page: form.page,
            nl: None,
        })
        .await
    {
        Ok(operation) => Redirect::to(&operation_url(operation.id)).into_response(),
        Err(error) => error_page(&error),
    }
}

async fn start_eh_reader_fetch(
    State(state): State<ControlState>,
    Form(form): Form<EhPageFetchForm>,
) -> Response {
    let profile = form.profile.clone();
    let token = form.token.clone();
    match state
        .core
        .start_eh_page_fetch(EhPageFetchRequest {
            profile: ProfileKey::new("eh", form.profile),
            gallery: crate::EhGalleryRef {
                gid: form.gid,
                token: form.token,
            },
            page: form.page,
            nl: None,
        })
        .await
    {
        Ok(operation) => Redirect::to(&eh_reader_url(
            &profile,
            form.gid,
            &token,
            form.page,
            Some(operation.id),
        ))
        .into_response(),
        Err(error) => error_page(&error),
    }
}

async fn jump_eh_reader(Form(form): Form<EhReaderJumpForm>) -> Response {
    if form.page == 0 {
        return error_page(&CoreError::new(
            ErrorCode::InvalidInput,
            "阅读器页码必须从 1 开始",
            false,
        ));
    }
    Redirect::to(&eh_reader_url(
        &form.profile,
        form.gid,
        &form.token,
        form.page - 1,
        None,
    ))
    .into_response()
}

async fn search(State(state): State<ControlState>, Query(query): Query<SearchQuery>) -> Response {
    let form = search_form(&query);
    if !matches!(query.provider.as_str(), "danbooru" | "gelbooru") {
        return html_page(
            StatusCode::BAD_REQUEST,
            "Booru 搜索",
            &format!("{form}<p class=\"error\">不支持该 Booru Provider。</p>"),
            None,
        );
    }
    let key = ProfileKey::new(&query.provider, &query.profile);
    let result = match query.provider.as_str() {
        "danbooru" => {
            state
                .core
                .search_danbooru(&key, &query.tags, query.page, query.limit)
                .await
        }
        "gelbooru" => {
            state
                .core
                .search_gelbooru(&key, &query.tags, query.page, query.limit)
                .await
        }
        _ => unreachable!(),
    };
    let result = match result {
        Ok(result) => result,
        Err(error) => {
            return html_page(
                error_status(&error),
                "Booru 搜索",
                &format!(
                    "{form}<p class=\"error\"><strong>{}</strong>: {}</p>",
                    error.code(),
                    escape(error.message())
                ),
                None,
            );
        }
    };
    let mut cards = String::new();
    for post in &result.posts {
        let detail = post_url(&query.provider, &query.profile, post.id);
        let tags = post
            .general_tags
            .iter()
            .take(8)
            .cloned()
            .collect::<Vec<_>>()
            .join(" ");
        let _ = write!(
            cards,
            "<article class=\"card\"><h2><a href=\"{}\">帖子 {}</a></h2><p>{} x {} · 评分 {} · 分级 {}</p><p class=\"muted\">{}</p></article>",
            escape(&detail),
            post.id,
            optional_number(post.original.width),
            optional_number(post.original.height),
            post.score,
            escape(&post.rating),
            escape(&tags),
        );
    }
    if cards.is_empty() {
        cards.push_str("<p class=\"muted\">没有返回帖子。</p>");
    }
    let mut paging = String::new();
    if result.page > 0 {
        let previous = search_url(
            &query.provider,
            &query.profile,
            &query.tags,
            result.page.saturating_sub(1),
            query.limit,
        );
        let _ = write!(paging, "<a href=\"{}\">上一页</a> ", escape(&previous));
    }
    if let Some(next) = result.next_page {
        let next = search_url(
            &query.provider,
            &query.profile,
            &query.tags,
            next,
            query.limit,
        );
        let _ = write!(paging, "<a href=\"{}\">下一页</a>", escape(&next));
    }
    let favorites = match state.core.favorite_searches() {
        Ok(favorites) => favorites,
        Err(error) => return error_page(&error),
    };
    let mut favorite_links = String::new();
    for favorite in favorites
        .iter()
        .filter(|favorite| favorite.provider == query.provider)
    {
        let _ = write!(
            favorite_links,
            "<li><a href=\"{}\">{}</a><form class=\"inline-form\" method=\"post\" action=\"/ui/favorite-search/delete\"><input type=\"hidden\" name=\"id\" value=\"{}\"><input type=\"hidden\" name=\"provider\" value=\"{}\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"query\" value=\"{}\"><button type=\"submit\">删除</button></form></li>",
            escape(&favorite_search_url(
                &favorite.provider,
                &favorite.profile,
                &favorite.query,
            )),
            escape(&favorite.name),
            favorite.id,
            escape(&favorite.provider),
            escape(&favorite.profile),
            escape(&favorite.query),
        );
    }
    if favorite_links.is_empty() {
        favorite_links.push_str("<li class=\"muted\">当前 Provider 尚无收藏搜索。</li>");
    }
    let save = if query.tags.trim().is_empty() {
        String::new()
    } else {
        format!(
            "<form method=\"post\" action=\"/ui/favorite-search\"><input type=\"hidden\" name=\"provider\" value=\"{}\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"query\" value=\"{}\"><label>收藏名称<input name=\"name\" value=\"{}\" required maxlength=\"120\"></label><button type=\"submit\">收藏当前搜索</button></form>",
            escape(&query.provider),
            escape(&query.profile),
            escape(&query.tags),
            escape(&query.tags),
        )
    };
    html_page(
        StatusCode::OK,
        "Booru 搜索",
        &format!(
            "<h1>Booru 搜索</h1>{form}{save}<section class=\"card\"><h2>{} 收藏搜索</h2><ul>{favorite_links}</ul></section><p>代次 {} · 第 {} 页 · {} 个帖子</p><p>{paging}</p><div class=\"grid\">{cards}</div><p>{paging}</p>",
            provider_name(&query.provider),
            result.generation,
            result.page,
            result.posts.len(),
        ),
        None,
    )
}

async fn post_detail(
    State(state): State<ControlState>,
    Query(query): Query<PostQuery>,
) -> Response {
    let key = ProfileKey::new(&query.provider, &query.profile);
    let post = match query.provider.as_str() {
        "danbooru" => state.core.danbooru_post(&key, query.id).await,
        "gelbooru" => state.core.gelbooru_post(&key, query.id).await,
        _ => Err(CoreError::new(
            ErrorCode::InvalidInput,
            "不支持该 Booru Provider",
            false,
        )),
    };
    match post {
        Ok(post) => html_page(
            StatusCode::OK,
            &format!("帖子 {}", post.id),
            &render_post(&query.profile, &post),
            None,
        ),
        Err(error) => error_page(&error),
    }
}

async fn start_fetch(State(state): State<ControlState>, Form(form): Form<FetchForm>) -> Response {
    let result = state
        .core
        .start_booru_original_fetch(BooruOriginalFetchRequest {
            profile: ProfileKey::new(form.provider, form.profile),
            post_id: form.post_id,
        })
        .await;
    match result {
        Ok(operation) => Redirect::to(&operation_url(operation.id)).into_response(),
        Err(error) => error_page(&error),
    }
}

async fn pixiv_detail(
    State(state): State<ControlState>,
    Query(query): Query<PixivQuery>,
) -> Response {
    let illust = match state
        .core
        .pixiv_illust(&ProfileKey::new("pixiv", &query.profile), &query.id)
        .await
    {
        Ok(illust) => illust,
        Err(error) => return error_page(&error),
    };
    let mut pages = String::new();
    for page in &illust.pages {
        let _ = write!(
            pages,
            "<article class=\"card\"><h2>第 {} 页</h2><p><code>{}</code></p><form method=\"post\" action=\"/ui/pixiv/fetch\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"illust_id\" value=\"{}\"><input type=\"hidden\" name=\"page\" value=\"{}\"><button type=\"submit\">获取原图</button></form></article>",
            page.index + 1,
            escape(page.original_url.as_str()),
            escape(&query.profile),
            escape(&illust.id),
            page.index,
        );
    }
    html_page(
        StatusCode::OK,
        &format!("Pixiv 作品 {}", illust.id),
        &format!(
            "<h1>{}</h1><p><a href=\"{}\">打开 Pixiv 页面</a></p><table><tr><th>作品 ID</th><td>{}</td></tr><tr><th>作者</th><td>{} ({})</td></tr><tr><th>页数</th><td>{}</td></tr><tr><th>尺寸</th><td>{} x {}</td></tr><tr><th>浏览 / 收藏</th><td>{} / {}</td></tr><tr><th>标签</th><td>{}</td></tr><tr><th>说明</th><td>{}</td></tr></table><div class=\"grid\">{pages}</div>",
            escape(&illust.title),
            escape(illust.page_url.as_str()),
            escape(&illust.id),
            escape(&illust.user.name),
            escape(&illust.user.id),
            illust.page_count,
            illust.width,
            illust.height,
            illust.view_count,
            illust.bookmark_count,
            escape(&illust.tags.join(" ")),
            escape(&illust.caption),
        ),
        None,
    )
}

async fn pixiv_search(
    State(state): State<ControlState>,
    Query(query): Query<PixivSearchQuery>,
) -> Response {
    let result = match state
        .core
        .search_pixiv(
            &ProfileKey::new("pixiv", &query.profile),
            &query.query,
            query.page,
        )
        .await
    {
        Ok(result) => result,
        Err(error) => return error_page(&error),
    };
    let mut cards = String::new();
    for item in &result.items {
        let _ = write!(
            cards,
            "<article class=\"card\"><h2><a href=\"{}\">{}</a></h2><p>作品 {} · 作者 {} ({}) · {} 页 · R18 {}</p><p class=\"muted\">{}</p></article>",
            escape(&pixiv_detail_url(&query.profile, &item.id)),
            escape(&item.title),
            escape(&item.id),
            escape(&item.user.name),
            escape(&item.user.id),
            item.page_count,
            item.x_restrict,
            escape(&item.tags.join(" ")),
        );
    }
    if cards.is_empty() {
        cards.push_str("<p class=\"muted\">没有返回 Pixiv 作品。</p>");
    }
    let next = result.next_page.map_or_else(String::new, |page| {
        format!(
            "<a href=\"{}\">下一页</a>",
            escape(&pixiv_search_url(&query.profile, &query.query, page))
        )
    });
    let previous = if result.page > 1 {
        format!(
            "<a href=\"{}\">上一页</a>",
            escape(&pixiv_search_url(
                &query.profile,
                &query.query,
                result.page - 1,
            ))
        )
    } else {
        String::new()
    };
    let favorites = match state.core.favorite_searches() {
        Ok(favorites) => favorites,
        Err(error) => return error_page(&error),
    };
    let mut favorite_links = String::new();
    for favorite in favorites
        .iter()
        .filter(|favorite| favorite.provider == "pixiv")
    {
        let _ = write!(
            favorite_links,
            "<li><a href=\"{}\">{}</a><form class=\"inline-form\" method=\"post\" action=\"/ui/favorite-search/delete\"><input type=\"hidden\" name=\"id\" value=\"{}\"><input type=\"hidden\" name=\"provider\" value=\"pixiv\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"query\" value=\"{}\"><button type=\"submit\">删除</button></form></li>",
            escape(&pixiv_search_url(&favorite.profile, &favorite.query, 1)),
            escape(&favorite.name),
            favorite.id,
            escape(&favorite.profile),
            escape(&favorite.query),
        );
    }
    if favorite_links.is_empty() {
        favorite_links.push_str("<li class=\"muted\">尚无 Pixiv 收藏搜索。</li>");
    }
    html_page(
        StatusCode::OK,
        "Pixiv 搜索",
        &format!(
            "<h1>Pixiv 搜索</h1><form method=\"get\" action=\"/ui/pixiv/search\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"page\" value=\"1\"><label>标签<input name=\"query\" value=\"{}\" required maxlength=\"500\"></label><button type=\"submit\">搜索</button></form><form method=\"post\" action=\"/ui/favorite-search\"><input type=\"hidden\" name=\"provider\" value=\"pixiv\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"query\" value=\"{}\"><label>收藏名称<input name=\"name\" value=\"{}\" required maxlength=\"120\"></label><button type=\"submit\">收藏当前搜索</button></form><section class=\"card\"><h2>Pixiv 收藏搜索</h2><ul>{favorite_links}</ul></section><p>代次 {} · 第 {} / {} 页 · {} 个作品</p><p>{previous} {next}</p><div class=\"grid\">{cards}</div><p>{previous} {next}</p>",
            escape(&query.profile),
            escape(&query.query),
            escape(&query.profile),
            escape(&query.query),
            escape(&query.query),
            result.generation,
            result.page,
            result.last_page,
            result.items.len(),
        ),
        None,
    )
}

async fn pixiv_ranking(
    State(state): State<ControlState>,
    Query(query): Query<PixivRankingQuery>,
) -> Response {
    let result = match state
        .core
        .pixiv_ranking(
            &ProfileKey::new("pixiv", &query.profile),
            &query.mode,
            &query.date,
            query.page,
        )
        .await
    {
        Ok(result) => result,
        Err(error) => return error_page(&error),
    };
    let mut cards = String::new();
    for item in &result.items {
        let previous_rank = item
            .previous_rank
            .map_or_else(|| "-".to_owned(), |rank| rank.to_string());
        let _ = write!(
            cards,
            "<article class=\"card\"><h2>#{} <a href=\"{}\">{}</a></h2><p>上期 {} · 作品 {} · 作者 {} ({}) · {} 页 · R18 {}</p><p class=\"muted\">{}</p></article>",
            item.rank,
            escape(&pixiv_detail_url(&query.profile, &item.id)),
            escape(&item.title),
            previous_rank,
            escape(&item.id),
            escape(&item.user.name),
            escape(&item.user.id),
            item.page_count,
            item.x_restrict,
            escape(&item.tags.join(" ")),
        );
    }
    if cards.is_empty() {
        cards.push_str("<p class=\"muted\">没有返回 Pixiv 排行作品。</p>");
    }
    let next = result.next_page.map_or_else(String::new, |page| {
        format!(
            "<a href=\"{}\">下一页</a>",
            escape(&pixiv_ranking_url(
                &query.profile,
                &result.mode,
                &result.date,
                page,
            ))
        )
    });
    let previous = if result.page > 1 {
        format!(
            "<a href=\"{}\">上一页</a>",
            escape(&pixiv_ranking_url(
                &query.profile,
                &result.mode,
                &result.date,
                result.page - 1,
            ))
        )
    } else {
        String::new()
    };
    let date_label = if result.date.is_empty() {
        "当前".to_owned()
    } else {
        escape(&result.date)
    };
    html_page(
        StatusCode::OK,
        "Pixiv 排行",
        &format!(
            "<h1>Pixiv 排行</h1><form method=\"get\" action=\"/ui/pixiv/ranking\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"page\" value=\"1\"><label>模式<select name=\"mode\"><option value=\"day\"{}>日榜</option><option value=\"week\"{}>周榜</option><option value=\"month\"{}>月榜</option></select></label><label>日期（可选）<input name=\"date\" type=\"date\" value=\"{}\"></label><button type=\"submit\">查看排行</button></form><p>会话 {} · 代次 {} · 模式 {} · 日期 {} · 第 {} 页 · {} 个作品</p><p>{previous} {next}</p><div class=\"grid\">{cards}</div><p>{previous} {next}</p>",
            escape(&query.profile),
            selected(result.mode == "day"),
            selected(result.mode == "week"),
            selected(result.mode == "month"),
            escape(&result.date),
            escape(&result.profile),
            result.generation,
            escape(&result.mode),
            date_label,
            result.page,
            result.items.len(),
        ),
        None,
    )
}

async fn pixiv_recommendations(
    State(state): State<ControlState>,
    Query(query): Query<PixivProfileQuery>,
) -> Response {
    let result = match state
        .core
        .pixiv_recommendations(&ProfileKey::new("pixiv", &query.profile))
        .await
    {
        Ok(result) => result,
        Err(error) => return error_page(&error),
    };
    let mut cards = String::new();
    for item in &result.items {
        let _ = write!(
            cards,
            "<article class=\"card\"><h2><a href=\"{}\">{}</a></h2><p>作品 {} · 作者 {} ({}) · {} 页 · R18 {}</p><p class=\"muted\">{}</p></article>",
            escape(&pixiv_detail_url(&query.profile, &item.id)),
            escape(&item.title),
            escape(&item.id),
            escape(&item.user.name),
            escape(&item.user.id),
            item.page_count,
            item.x_restrict,
            escape(&item.tags.join(" ")),
        );
    }
    if cards.is_empty() {
        cards.push_str("<p class=\"muted\">当前没有返回 Pixiv 推荐作品。</p>");
    }
    html_page(
        StatusCode::OK,
        "Pixiv 推荐",
        &format!(
            "<h1>Pixiv 推荐</h1><p>会话 {} · 代次 {} · {} 个作品</p><p><a href=\"{}\">刷新当前推荐</a></p><div class=\"grid\">{cards}</div>",
            escape(&result.profile),
            result.generation,
            result.items.len(),
            escape(&pixiv_recommendations_url(&query.profile)),
        ),
        None,
    )
}

async fn pixiv_following(
    State(state): State<ControlState>,
    Query(query): Query<PixivFollowingQuery>,
) -> Response {
    let result = match state
        .core
        .pixiv_following(
            &ProfileKey::new("pixiv", &query.profile),
            query.visibility,
            query.page,
        )
        .await
    {
        Ok(result) => result,
        Err(error) => return error_page(&error),
    };
    let mut cards = String::new();
    for item in &result.items {
        let _ = write!(
            cards,
            "<article class=\"card\"><h2><a href=\"{}\">{}</a></h2><p>作品 {} · 作者 {} ({}) · {} 页 · R18 {}</p><p class=\"muted\">{}</p></article>",
            escape(&pixiv_detail_url(&query.profile, &item.id)),
            escape(&item.title),
            escape(&item.id),
            escape(&item.user.name),
            escape(&item.user.id),
            item.page_count,
            item.x_restrict,
            escape(&item.tags.join(" ")),
        );
    }
    if cards.is_empty() {
        cards.push_str("<p class=\"muted\">当前没有返回 Pixiv 关注作品。</p>");
    }
    let next = result.next_page.map_or_else(String::new, |page| {
        format!(
            "<a href=\"{}\">下一页</a>",
            escape(&pixiv_following_url(
                &query.profile,
                result.visibility,
                page,
            ))
        )
    });
    let previous = if result.page > 1 {
        format!(
            "<a href=\"{}\">上一页</a>",
            escape(&pixiv_following_url(
                &query.profile,
                result.visibility,
                result.page - 1,
            ))
        )
    } else {
        String::new()
    };
    html_page(
        StatusCode::OK,
        "Pixiv 关注",
        &format!(
            "<h1>Pixiv 关注</h1><p class=\"muted\">需要当前 Pixiv profile 已加载登录 Cookie。</p><form method=\"get\" action=\"/ui/pixiv/following\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"page\" value=\"1\"><label>范围<select name=\"visibility\"><option value=\"public\"{}>公开关注</option><option value=\"private\"{}>R18 关注</option></select></label><button type=\"submit\">查看关注</button></form><p>会话 {} · 代次 {} · 第 {} 页 · {} 个作品</p><p>{previous} {next}</p><div class=\"grid\">{cards}</div><p>{previous} {next}</p>",
            escape(&query.profile),
            selected(result.visibility == crate::PixivFollowingVisibility::Public),
            selected(result.visibility == crate::PixivFollowingVisibility::Private),
            escape(&result.profile),
            result.generation,
            result.page,
            result.items.len(),
        ),
        None,
    )
}

async fn start_pixiv_fetch(
    State(state): State<ControlState>,
    Form(form): Form<PixivFetchForm>,
) -> Response {
    match state
        .core
        .start_pixiv_page_fetch(PixivPageFetchRequest {
            profile: ProfileKey::new("pixiv", form.profile),
            illust_id: form.illust_id,
            page: form.page,
        })
        .await
    {
        Ok(operation) => Redirect::to(&operation_url(operation.id)).into_response(),
        Err(error) => error_page(&error),
    }
}

async fn operations(State(state): State<ControlState>) -> Response {
    let operations = match state.core.operations().await {
        Ok(operations) => operations,
        Err(error) => return error_page(&error),
    };
    let mut rows = String::new();
    for operation in operations.iter().rev() {
        let _ = write!(
            rows,
            "<tr><td><a href=\"{}\"><code>{}</code></a></td><td>{:?}</td><td>{:?}</td><td>{}</td><td>{}{}</td></tr>",
            escape(&operation_url(operation.id)),
            operation.id,
            operation.kind,
            operation.state,
            escape(&operation.phase),
            operation.bytes_done,
            operation
                .bytes_total
                .map_or_else(String::new, |total| format!(" / {total}"))
        );
    }
    if rows.is_empty() {
        rows.push_str("<tr><td colspan=\"5\" class=\"muted\">暂无操作。</td></tr>");
    }
    let refresh = operations
        .iter()
        .any(|operation| !operation.state.is_terminal())
        .then_some(OPERATIONS_REFRESH_SECONDS);
    html_page(
        StatusCode::OK,
        "操作列表",
        &format!(
            "<h1>操作列表</h1><table><thead><tr><th>ID</th><th>类型</th><th>状态</th><th>阶段</th><th>字节</th></tr></thead><tbody>{rows}</tbody></table>"
        ),
        refresh,
    )
}

async fn operation(
    State(state): State<ControlState>,
    Query(query): Query<OperationQuery>,
) -> Response {
    let id = match query.id.parse() {
        Ok(id) => id,
        Err(_) => {
            return error_page(&CoreError::new(
                ErrorCode::InvalidInput,
                "操作 ID 必须是有效的 UUID",
                false,
            ));
        }
    };
    let operation = match state.core.operation(id).await {
        Ok(operation) => operation,
        Err(error) => return error_page(&error),
    };
    let refresh = (!operation.state.is_terminal()).then_some(OPERATION_REFRESH_SECONDS);
    html_page(
        StatusCode::OK,
        "操作详情",
        &render_operation(&operation),
        refresh,
    )
}

async fn cancel_operation(
    State(state): State<ControlState>,
    Form(form): Form<CancelForm>,
) -> Response {
    let id = match form.id.parse() {
        Ok(id) => id,
        Err(_) => {
            return error_page(&CoreError::new(
                ErrorCode::InvalidInput,
                "操作 ID 必须是有效的 UUID",
                false,
            ));
        }
    };
    match state.core.cancel_operation(id).await {
        Ok(_) => Redirect::to(&operation_url(id)).into_response(),
        Err(error) => error_page(&error),
    }
}

fn search_form(query: &SearchQuery) -> String {
    let danbooru_selected = if query.provider == "danbooru" {
        " selected"
    } else {
        ""
    };
    let gelbooru_selected = if query.provider == "gelbooru" {
        " selected"
    } else {
        ""
    };
    format!(
        "<form method=\"get\" action=\"/ui/search\"><label>Provider<select name=\"provider\"><option value=\"danbooru\"{danbooru_selected}>Danbooru</option><option value=\"gelbooru\"{gelbooru_selected}>Gelbooru</option></select></label><label>会话名称<input name=\"profile\" value=\"{}\" required></label><label>标签<input name=\"tags\" value=\"{}\"></label><label>每页数量<input name=\"limit\" type=\"number\" min=\"1\" max=\"100\" value=\"{}\"></label><input type=\"hidden\" name=\"page\" value=\"1\"><button type=\"submit\">搜索</button></form>",
        escape(&query.profile),
        escape(&query.tags),
        query.limit,
    )
}

fn render_post(profile: &str, post: &BooruPost) -> String {
    let tags = post
        .general_tags
        .iter()
        .chain(&post.artist_tags)
        .chain(&post.character_tags)
        .map(|tag| escape(tag))
        .collect::<Vec<_>>()
        .join(" ");
    format!(
        "<h1>{} 帖子 {}</h1><p><a href=\"{}\">打开 Provider 页面</a></p><table><tr><th>原图</th><td>{} x {}, {} 字节</td></tr><tr><th>MD5</th><td><code>{}</code></td></tr><tr><th>扩展名</th><td>{}</td></tr><tr><th>分级 / 评分</th><td>{} / {}</td></tr><tr><th>来源</th><td>{}</td></tr><tr><th>标签</th><td>{}</td></tr></table><form method=\"post\" action=\"/ui/fetch\"><input type=\"hidden\" name=\"provider\" value=\"{}\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"post_id\" value=\"{}\"><button type=\"submit\">获取并校验原图</button></form>",
        escape(&post.provider),
        post.id,
        escape(post.page_url.as_str()),
        optional_number(post.original.width),
        optional_number(post.original.height),
        post.original
            .byte_length
            .map_or_else(|| "未知".to_owned(), |value| value.to_string()),
        escape(post.original_md5.as_deref().unwrap_or("不可用")),
        escape(post.file_extension.as_deref().unwrap_or("未知")),
        escape(&post.rating),
        post.score,
        escape(post.source.as_deref().unwrap_or("")),
        tags,
        escape(&post.provider),
        escape(profile),
        post.id,
    )
}

fn render_operation(operation: &OperationSnapshot) -> String {
    let error = operation.error.as_ref().map_or_else(String::new, |error| {
        format!(
            "<p class=\"error\"><strong>{}</strong>: {}</p>",
            error.code,
            escape(&error.message)
        )
    });
    let result = operation.resource.as_ref().map_or_else(String::new, |resource| {
        let url = format!("/api/v1/resources/images/{}/{}", resource.content_md5, resource.extension);
        format!("<h2>结果</h2><p><code>{}</code> · {} · {} 字节 · {:?} · 已持久化 {}</p><p><a href=\"{}\">打开资源</a></p><img class=\"resource\" src=\"{}\" alt=\"已获取图片\">", resource.content_md5, escape(&resource.mime_type), resource.byte_length, resource.source, yes_no(resource.cache_persisted), escape(&url), escape(&url))
    });
    let cancel = if operation.state.is_terminal() {
        String::new()
    } else {
        format!(
            "<form method=\"post\" action=\"/ui/cancel\"><input type=\"hidden\" name=\"id\" value=\"{}\"><button type=\"submit\">取消操作</button></form>",
            operation.id
        )
    };
    format!(
        "<h1>操作详情</h1><p><code>{}</code></p><table><tr><th>类型</th><td>{:?}</td></tr><tr><th>资源目标</th><td><code>{}</code></td></tr><tr><th>状态</th><td>{:?}</td></tr><tr><th>阶段</th><td>{}</td></tr><tr><th>修订号</th><td>{}</td></tr><tr><th>字节</th><td>{}{}</td></tr><tr><th>来源</th><td>{:?}</td></tr><tr><th>共享传输</th><td>{}</td></tr></table>{error}{cancel}{result}",
        operation.id,
        operation.kind,
        escape(&operation.resource_key.as_ref().map_or_else(
            || "-".to_owned(),
            |key| format!(
                "{}:{}:{}:{}",
                key.provider, key.media, key.page, key.variant
            ),
        )),
        operation.state,
        escape(&operation.phase),
        operation.revision,
        operation.bytes_done,
        operation
            .bytes_total
            .map_or_else(String::new, |total| format!(" / {total}")),
        operation.source,
        yes_no(operation.shared)
    )
}

fn html_page(status: StatusCode, title: &str, body: &str, refresh: Option<u64>) -> Response {
    let refresh_meta = refresh.map_or_else(String::new, |seconds| {
        format!("<meta http-equiv=\"refresh\" content=\"{seconds}\">")
    });
    let refresh_status = refresh.map_or_else(
        || "<span class=\"refresh-status muted\">自动刷新已停止</span>".to_owned(),
        |seconds| {
            format!(
                "<span class=\"refresh-status live\" role=\"status\">每 {seconds} 秒自动刷新</span>"
            )
        },
    );
    let refresh_action = refresh.map_or_else(String::new, |_| {
        "<a class=\"refresh-action\" href=\"\">立即刷新</a>".to_owned()
    });
    let html = format!(
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">{refresh_meta}<title>{}</title><style>{STYLE}</style></head><body><nav><div class=\"nav-links\"><a href=\"/\">调试面板</a><a href=\"/ui/eh?profile=default\">EH 主页</a><a href=\"/ui/search\">搜索</a><a href=\"/ui/operations\">操作列表</a><a href=\"/ui/archive-tasks\">Archive 任务</a><a href=\"/ui/local-galleries\">本地画廊</a><a href=\"/ui/local-data\">本地数据</a><a href=\"/ui/cache\">图片缓存</a><a href=\"/ui/config\">配置</a></div><div class=\"refresh-control\">{refresh_status}{refresh_action}</div></nav><main>{body}</main></body></html>",
        escape(title)
    );
    let mut response = (status, Html(html)).into_response();
    let headers = response.headers_mut();
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    headers.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    headers.insert(header::CONTENT_SECURITY_POLICY, HeaderValue::from_static("default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"));
    response
}

fn error_page(error: &CoreError) -> Response {
    html_page(
        error_status(error),
        "fvcore 错误",
        &format!(
            "<h1>请求失败</h1><p class=\"error\"><strong>{}</strong>: {}</p>",
            error.code(),
            escape(error.message())
        ),
        None,
    )
}

fn error_status(error: &CoreError) -> StatusCode {
    match error.code() {
        ErrorCode::InvalidInput | ErrorCode::InvalidConfig | ErrorCode::Parse => {
            StatusCode::BAD_REQUEST
        }
        ErrorCode::OperationNotFound | ErrorCode::ProfileNotFound | ErrorCode::ResourceNotFound => {
            StatusCode::NOT_FOUND
        }
        ErrorCode::AuthenticationRequired => StatusCode::UNAUTHORIZED,
        ErrorCode::AccessDenied => StatusCode::FORBIDDEN,
        ErrorCode::OperationFinished => StatusCode::CONFLICT,
        ErrorCode::Overloaded | ErrorCode::RateLimited => StatusCode::TOO_MANY_REQUESTS,
        ErrorCode::NotReady => StatusCode::SERVICE_UNAVAILABLE,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    }
}

fn editing(query: &ConfigurationQuery, field: &str, provider: &str, profile: &str) -> bool {
    query.edit.as_deref() == Some(field)
        && query.provider.as_deref() == Some(provider)
        && query.profile.as_deref() == Some(profile)
}

fn setting_display(value: &str, edit_url: &str) -> String {
    format!(
        "<div class=\"setting-display\"><pre>{}</pre><a class=\"setting-edit\" href=\"{}\">编辑</a></div>",
        escape(if value.is_empty() { "未配置" } else { value }),
        escape(edit_url),
    )
}

fn config_edit_url(field: &str, provider: &str, profile: &str) -> String {
    let query = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("edit", field)
        .append_pair("provider", provider)
        .append_pair("profile", profile)
        .finish();
    format!("/ui/config?{query}")
}

fn search_url(provider: &str, profile: &str, tags: &str, page: u64, limit: u32) -> String {
    let query = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("provider", provider)
        .append_pair("profile", profile)
        .append_pair("tags", tags)
        .append_pair("page", &page.to_string())
        .append_pair("limit", &limit.to_string())
        .finish();
    format!("/ui/search?{query}")
}

fn post_url(provider: &str, profile: &str, id: u64) -> String {
    let query = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("provider", provider)
        .append_pair("profile", profile)
        .append_pair("id", &id.to_string())
        .finish();
    format!("/ui/post?{query}")
}

fn eh_reader_url(
    profile: &str,
    gid: u64,
    token: &str,
    page: u32,
    operation: Option<crate::OperationId>,
) -> String {
    let mut query = url::form_urlencoded::Serializer::new(String::new());
    query
        .append_pair("profile", profile)
        .append_pair("gid", &gid.to_string())
        .append_pair("token", token)
        .append_pair("page", &page.to_string());
    if let Some(operation) = operation {
        query.append_pair("operation", &operation.to_string());
    }
    format!("/ui/eh/reader?{}", query.finish())
}

fn eh_reader_fetch_form(query: &EhReaderQuery) -> String {
    format!(
        "<form class=\"reader-fetch\" method=\"post\" action=\"/ui/eh/reader/fetch\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"gid\" value=\"{}\"><input type=\"hidden\" name=\"token\" value=\"{}\"><input type=\"hidden\" name=\"page\" value=\"{}\"><button type=\"submit\">获取第 {} 页阅读器图片</button></form>",
        escape(&query.profile),
        query.gid,
        escape(&query.token),
        query.page,
        query.page + 1,
    )
}

fn reader_navigation(previous: Option<&str>, next: Option<&str>) -> String {
    let previous = previous.map_or_else(
        || "<span class=\"disabled\">上一页</span>".to_owned(),
        |url| {
            format!(
                "<a rel=\"prev\" accesskey=\"j\" href=\"{}\">上一页</a>",
                escape(url)
            )
        },
    );
    let next = next.map_or_else(
        || "<span class=\"disabled\">下一页</span>".to_owned(),
        |url| {
            format!(
                "<a rel=\"next\" accesskey=\"k\" href=\"{}\">下一页</a>",
                escape(url)
            )
        },
    );
    format!("<nav class=\"reader-nav\">{previous}{next}</nav>")
}

fn operation_url(id: crate::OperationId) -> String {
    format!("/ui/operation?id={id}")
}

fn local_gallery_url(id: uuid::Uuid, offset: u32) -> String {
    format!("/ui/local-gallery?id={id}&offset={offset}")
}

fn eh_home_url(profile: &str, search: &str, cursor: Option<crate::EhPageCursor>) -> String {
    let mut query = url::form_urlencoded::Serializer::new(String::new());
    query.append_pair("profile", profile);
    if !search.is_empty() {
        query.append_pair("search", search);
    }
    if let Some(cursor) = cursor {
        query.append_pair(
            "direction",
            match cursor.direction {
                crate::EhPageDirection::Previous => "previous",
                crate::EhPageDirection::Next => "next",
            },
        );
        query.append_pair("gid", &cursor.gid.to_string());
    }
    format!("/ui/eh?{}", query.finish())
}

fn favorite_search_url(provider: &str, profile: &str, query: &str) -> String {
    if provider == "eh" {
        eh_home_url(profile, query, None)
    } else if provider == "pixiv" {
        pixiv_search_url(profile, query, 1)
    } else {
        search_url(provider, profile, query, 1, 40)
    }
}

fn pixiv_search_url(profile: &str, query: &str, page: u32) -> String {
    let query = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("profile", profile)
        .append_pair("query", query)
        .append_pair("page", &page.to_string())
        .finish();
    format!("/ui/pixiv/search?{query}")
}

fn pixiv_ranking_url(profile: &str, mode: &str, date: &str, page: u32) -> String {
    let query = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("profile", profile)
        .append_pair("mode", mode)
        .append_pair("date", date)
        .append_pair("page", &page.to_string())
        .finish();
    format!("/ui/pixiv/ranking?{query}")
}

fn pixiv_recommendations_url(profile: &str) -> String {
    let query = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("profile", profile)
        .finish();
    format!("/ui/pixiv/recommendations?{query}")
}

fn pixiv_following_url(
    profile: &str,
    visibility: crate::PixivFollowingVisibility,
    page: u32,
) -> String {
    let visibility = match visibility {
        crate::PixivFollowingVisibility::Public => "public",
        crate::PixivFollowingVisibility::Private => "private",
    };
    let query = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("profile", profile)
        .append_pair("visibility", visibility)
        .append_pair("page", &page.to_string())
        .finish();
    format!("/ui/pixiv/following?{query}")
}

fn pixiv_detail_url(profile: &str, id: &str) -> String {
    let query = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("profile", profile)
        .append_pair("id", id)
        .finish();
    format!("/ui/pixiv?{query}")
}

const fn default_page_one() -> u32 {
    1
}

fn default_pixiv_ranking_mode() -> String {
    "day".to_owned()
}

const fn default_pixiv_following_visibility() -> crate::PixivFollowingVisibility {
    crate::PixivFollowingVisibility::Public
}

const fn selected(value: bool) -> &'static str {
    if value { " selected" } else { "" }
}

fn eh_gallery_url(profile: &str, gid: u64, token: &str, page: u32) -> String {
    let query = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("profile", profile)
        .append_pair("gid", &gid.to_string())
        .append_pair("token", token)
        .append_pair("page", &page.to_string())
        .finish();
    format!("/ui/eh/gallery?{query}")
}

fn optional_number(value: Option<u32>) -> String {
    value.map_or_else(|| "?".to_owned(), |value| value.to_string())
}

fn yes_no(value: bool) -> &'static str {
    if value { "是" } else { "否" }
}

fn local_inventory_status(status: crate::LocalGalleryInventoryStatus) -> &'static str {
    match status {
        crate::LocalGalleryInventoryStatus::RegisteredHealthy => "已登记健康",
        crate::LocalGalleryInventoryStatus::RegisteredDamaged => "已登记损坏",
        crate::LocalGalleryInventoryStatus::UnregisteredImportable => "未登记可导入",
        crate::LocalGalleryInventoryStatus::Invalid => "格式无效",
    }
}

fn provider_capability(provider: &str) -> &'static str {
    match provider {
        "eh" => "主页 / 详情 / 缩略图 / Archive 选项",
        "pixiv" => "详情 / 多页原图",
        "danbooru" | "gelbooru" => "搜索 / 详情 / 原图",
        _ => "未知",
    }
}

fn provider_name(provider: &str) -> &'static str {
    match provider {
        "eh" => "EHentai",
        "pixiv" => "Pixiv",
        "danbooru" => "Danbooru",
        "gelbooru" => "Gelbooru",
        _ => "Provider",
    }
}

fn escape(input: &str) -> String {
    input
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&#39;")
}

#[cfg(test)]
mod tests {
    use super::escape;

    #[test]
    fn escapes_untrusted_html() {
        assert_eq!(escape("<a & \"b\">"), "&lt;a &amp; &quot;b&quot;&gt;");
    }
}

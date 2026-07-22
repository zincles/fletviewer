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
struct PixivFetchForm {
    profile: String,
    illust_id: String,
    page: u32,
}

#[derive(Deserialize)]
struct EhHomeQuery {
    profile: String,
    direction: Option<crate::EhPageDirection>,
    gid: Option<u64>,
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

pub(crate) fn routes() -> Router<ControlState> {
    Router::new()
        .route("/", get(dashboard))
        .route("/ui/search", get(search))
        .route("/ui/post", get(post_detail))
        .route("/ui/fetch", post(start_fetch))
        .route("/ui/pixiv", get(pixiv_detail))
        .route("/ui/pixiv/fetch", post(start_pixiv_fetch))
        .route("/ui/eh", get(eh_home))
        .route("/ui/eh/gallery", get(eh_gallery))
        .route("/ui/eh/fetch", post(start_eh_page_fetch))
        .route("/ui/eh/archive", post(start_eh_archive))
        .route("/ui/archive-tasks", get(archive_tasks))
        .route("/ui/local-galleries", get(local_galleries))
        .route("/ui/local-data", get(local_data))
        .route("/ui/local-data/import", post(import_local_gallery))
        .route("/ui/config", get(configuration))
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
                escape(&eh_home_url(&profile.key.profile, None)),
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
        "<form method=\"get\" action=\"/ui/pixiv\"><label>会话名称<input name=\"profile\" value=\"{}\" required></label><label>作品 ID<input name=\"id\" inputmode=\"numeric\" required></label><button type=\"submit\">查看作品详情</button></form>",
        escape(pixiv_profile),
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
        .eh_home(&ProfileKey::new("eh", &query.profile), cursor)
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
            escape(&eh_home_url(&query.profile, Some(previous)))
        );
    }
    if let Some(next) = page.next {
        let _ = write!(
            paging,
            "<a href=\"{}\">下一页</a>",
            escape(&eh_home_url(&query.profile, Some(next)))
        );
    }
    html_page(
        StatusCode::OK,
        "EH 主页",
        &format!(
            "<h1>EH 主页</h1><p>会话 <code>eh/{}</code> · 代次 {} · {} 个 Gallery</p><p>{paging}</p><div class=\"grid gallery-grid\">{galleries}</div><p>{paging}</p>",
            escape(&query.profile),
            page.generation,
            page.galleries.len(),
        ),
        None,
    )
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
            "<article class=\"card\"><h2>第 {} 页 · {} x {}</h2><p><a href=\"{}\" rel=\"noreferrer\">打开图片页</a></p><code>{}</code><form method=\"post\" action=\"/ui/eh/fetch\"><input type=\"hidden\" name=\"profile\" value=\"{}\"><input type=\"hidden\" name=\"gid\" value=\"{}\"><input type=\"hidden\" name=\"token\" value=\"{}\"><input type=\"hidden\" name=\"page\" value=\"{}\"><button type=\"submit\">获取原图</button></form></article>",
            item.page + 1,
            optional_number(item.width),
            optional_number(item.height),
            escape(item.page_url.as_str()),
            escape(&item.image_url),
            escape(&query.profile),
            query.gid,
            escape(&query.token),
            item.page,
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

async fn configuration(State(state): State<ControlState>) -> Response {
    let config = match state.core.effective_config().await {
        Ok(config) => config,
        Err(error) => return error_page(&error),
    };
    let mut profiles = String::new();
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
    }
    html_page(
        StatusCode::OK,
        "当前生效配置",
        &format!(
            "<h1>当前生效配置</h1><p class=\"muted\">此页只读且已脱敏：不显示 Cookie、API key、API user 或代理 URL/凭据值。</p><div class=\"grid\"><section class=\"card\"><h2>Runtime</h2><dl><dt>Schema</dt><dd>{}</dd><dt>实例</dt><dd>{}</dd><dt>命令容量</dt><dd>{}</dd><dt>关闭期限</dt><dd>{} 秒</dd></dl></section><section class=\"card\"><h2>HTTP</h2><dl><dt>启用</dt><dd>{}</dd><dt>监听</dt><dd><code>{}</code></dd><dt>WebUI</dt><dd>{}</dd></dl></section><section class=\"card\"><h2>网络</h2><dl><dt>连接 / 请求超时</dt><dd>{} / {} 秒</dd><dt>响应上限</dt><dd>{} 字节</dd><dt>重定向</dt><dd>{}</dd><dt>代理</dt><dd>{}</dd></dl></section><section class=\"card\"><h2>图片</h2><dl><dt>单图上限</dt><dd>{}</dd><dt>内存缓存</dt><dd>{}</dd><dt>在途字节</dt><dd>{}</dd><dt>写盘队列</dt><dd>{}</dd></dl></section><section class=\"card\"><h2>Operation</h2><dl><dt>活动上限</dt><dd>{}</dd><dt>排队上限</dt><dd>{}</dd><dt>终态保留</dt><dd>{}</dd><dt>默认期限</dt><dd>{} 秒</dd></dl></section><section class=\"card\"><h2>Event</h2><dl><dt>通道容量</dt><dd>{}</dd><dt>Journal 保留</dt><dd>{}</dd></dl></section><section class=\"card wide\"><h2>存储域</h2><table><tr><th>Schema</th><td>{}</td><th>数据库</th><td>{} 字节</td></tr><tr><th>Data</th><td colspan=\"3\"><code>{}</code></td></tr><tr><th>Cache</th><td colspan=\"3\"><code>{}</code></td></tr><tr><th>Downloads</th><td colspan=\"3\"><code>{}</code></td></tr><tr><th>Temp</th><td colspan=\"3\"><code>{}</code></td></tr></table></section><section class=\"card wide\"><h2>Provider 配置</h2><table><thead><tr><th>Profile</th><th>Origin</th><th>User-Agent</th><th>Redirect hosts</th><th>Cookie env / 已加载</th><th>API user + key env / 已加载</th><th>并发</th><th>间隔</th></tr></thead><tbody>{profiles}</tbody></table></section></div>",
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
    html_page(
        StatusCode::OK,
        "Booru 搜索",
        &format!(
            "<h1>Booru 搜索</h1>{form}<p>代次 {} · 第 {} 页 · {} 个帖子</p><p>{paging}</p><div class=\"grid\">{cards}</div><p>{paging}</p>",
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
        "<h1>操作详情</h1><p><code>{}</code></p><table><tr><th>类型</th><td>{:?}</td></tr><tr><th>状态</th><td>{:?}</td></tr><tr><th>阶段</th><td>{}</td></tr><tr><th>修订号</th><td>{}</td></tr><tr><th>字节</th><td>{}{}</td></tr><tr><th>来源</th><td>{:?}</td></tr><tr><th>共享传输</th><td>{}</td></tr></table>{error}{cancel}{result}",
        operation.id,
        operation.kind,
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
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">{refresh_meta}<title>{}</title><style>{STYLE}</style></head><body><nav><div class=\"nav-links\"><a href=\"/\">调试面板</a><a href=\"/ui/eh?profile=default\">EH 主页</a><a href=\"/ui/search\">搜索</a><a href=\"/ui/operations\">操作列表</a><a href=\"/ui/archive-tasks\">Archive 任务</a><a href=\"/ui/local-galleries\">本地画廊</a><a href=\"/ui/local-data\">本地数据</a><a href=\"/ui/config\">配置</a></div><div class=\"refresh-control\">{refresh_status}{refresh_action}</div></nav><main>{body}</main></body></html>",
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

fn operation_url(id: crate::OperationId) -> String {
    format!("/ui/operation?id={id}")
}

fn local_gallery_url(id: uuid::Uuid, offset: u32) -> String {
    format!("/ui/local-gallery?id={id}&offset={offset}")
}

fn eh_home_url(profile: &str, cursor: Option<crate::EhPageCursor>) -> String {
    let mut query = url::form_urlencoded::Serializer::new(String::new());
    query.append_pair("profile", profile);
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

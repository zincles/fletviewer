//! Optional server-rendered diagnostic WebUI.

use crate::{
    BooruOriginalFetchRequest, BooruPost, CoreError, ErrorCode, OperationSnapshot,
    PixivPageFetchRequest, ProfileKey, control::ControlState,
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
        pixiv_form,
        operation_rows,
    );
    html_page(StatusCode::OK, "调试面板", &body, None)
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
    html_page(
        StatusCode::OK,
        "操作列表",
        &format!(
            "<h1>操作列表</h1><table><thead><tr><th>ID</th><th>类型</th><th>状态</th><th>阶段</th><th>字节</th></tr></thead><tbody>{rows}</tbody></table>"
        ),
        None,
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
    let refresh = (!operation.state.is_terminal()).then_some(1);
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
    let refresh = refresh.map_or_else(String::new, |seconds| {
        format!("<meta http-equiv=\"refresh\" content=\"{seconds}\">")
    });
    let html = format!(
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">{refresh}<title>{}</title><style>{STYLE}</style></head><body><nav><a href=\"/\">调试面板</a><a href=\"/ui/search\">搜索</a><a href=\"/ui/operations\">操作列表</a></nav><main>{body}</main></body></html>",
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

fn optional_number(value: Option<u32>) -> String {
    value.map_or_else(|| "?".to_owned(), |value| value.to_string())
}

fn yes_no(value: bool) -> &'static str {
    if value { "是" } else { "否" }
}

fn provider_capability(provider: &str) -> &'static str {
    match provider {
        "eh" => "Archive 选项",
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

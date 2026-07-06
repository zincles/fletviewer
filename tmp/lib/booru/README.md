# tmp/lib/booru

Experimental Python port of the LoliSnatcher booru handler idea.

Scope rule:
- This package is isolated temporary work.
- Do not import it from the app yet.
- Do not touch EH code while experimenting here.

## Design

Protocol-specific clients under `providers/` perform HTTP and parsing:
- `DanbooruClient`: modern Danbooru JSON API.
- `GelbooruClient`: current `gelbooru.com` JSON DAPI.
- `GelbooruAlikeClient`: old Gelbooru-style XML DAPI.
- `SafebooruClient`: Gelbooru-alike preset.
- `Rule34Client`: Gelbooru-alike preset with separate API host.
- `MoebooruClient`: Moebooru XML API.

External code receives common models from `data/`:
- `BooruPost`
- `ImageVariant`
- `BooruSearchResult`
- `TagSuggestion`

## Example

```python
from tmp.lib.booru import create_booru_client

client = create_booru_client("danbooru")
result = client.search_posts("cat rating:safe", limit=5)

for post in result.posts:
    print(post.id, post.thumbnail_url, post.sample_url, post.original_url)
```

## Browser-Like Transport

Danbooru may block vanilla `requests` with Cloudflare, while `curl_cffi` Chrome impersonation works.

```python
from tmp.lib.booru import create_booru_client, create_browser_like_session

session = create_browser_like_session(impersonate="chrome")
client = create_booru_client("danbooru", session=session)
result = client.search_posts("cat rating:general", limit=3)
print(len(result.posts))
```

Install `curl_cffi` first for this path:

```powershell
pip install curl_cffi
```

## Pagination

```python
page = client.next_page(result)
next_result = client.search_posts(result.tags, page=page, limit=result.limit)
```

## Tags

```python
suggestions = client.tag_suggestions("hatsune", limit=10)
for tag in suggestions:
    print(tag.tag, tag.type, tag.count)
```

## Important

Booru sites are unified only at the Python adapter/model layer. The actual HTTP protocols remain separate.

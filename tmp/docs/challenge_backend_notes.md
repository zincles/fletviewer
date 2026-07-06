# Challenge Backend Notes

Temporary design note for Cloudflare/captcha session bootstrapping.

## Target Architecture

Provider requests should not know how a challenge is solved.

```text
provider client
-> browser_session/request transport
-> challenge detector
-> challenge backend
-> cookie import
-> retry request once
```

## Platform Backends

- Mobile: native WebView backend. User completes challenge in WebView, app reads WebView cookies, then imports cookies into the HTTP session.
- PC desktop: Camoufox backend. Launch browser, complete challenge, export cookies and user-agent, import them into the HTTP session.
- Web/server mode: manual cookie import first. Camoufox can be optional on the server, but only if the server can run a browser and the target session belongs to the server IP.

## Cookie Handoff

The useful artifact is not the WebView itself. The useful artifact is:

```text
domain cookies + user-agent + target origin
```

After solving a challenge, normal provider code should continue using the lightweight HTTP client/session.

## Camoufox Probe

Run from project root after installing Camoufox:

```powershell
pip install camoufox
python -m camoufox fetch
python tmp/probes/camoufox_danbooru_probe.py
```

Use headless mode only as an experiment:

```powershell
python tmp/probes/camoufox_danbooru_probe.py --headless
```

Visible mode is more useful for challenges that require interaction.

## Danbooru Probe Result

Observed on Windows with:

```text
camoufox 0.4.11
playwright 1.61.0
```

Initial `browser.new_page()` failed because Playwright sent a `viewport.isMobile` field rejected by Camoufox's protocol schema. Workaround: create a browser context with `no_viewport=True`, then create the page from that context.

```python
context = browser.new_context(no_viewport=True)
page = context.new_page()
```

Result:

- Camoufox can open `https://danbooru.donmai.us/`.
- Camoufox can directly open `https://danbooru.donmai.us/posts.json?...` and receive JSON.
- Exported cookies only included `_danbooru2_session`, not `cf_clearance`.
- Importing Camoufox cookies and user-agent into `requests.Session` still returned Cloudflare `403 Just a moment...` for `/posts.json`.

Interpretation:

- Danbooru access succeeded inside the browser environment.
- The successful browser state was not transferable to vanilla `requests` by cookies + user-agent alone.
- For PC/server challenge handling, Camoufox may need to be treated as a transport/fetch backend for protected requests, not only as a cookie bootstrapper.
- A lighter next experiment is `curl_cffi` with Chrome/Firefox impersonation to see whether a browser-like TLS/HTTP fingerprint is enough for `/posts.json` without keeping Camoufox in the data path.

## curl_cffi Probe

Probe file:

```text
tmp/probes/curl_cffi_danbooru_probe.py
```

Install and run:

```powershell
pip install curl_cffi
python tmp/probes/curl_cffi_danbooru_probe.py
```

This tests multiple impersonation presets against Danbooru `/posts.json`:

```text
chrome
chrome124
chrome120
chrome110
safari
safari17_0
firefox
```

Expected interpretation:

- If one preset returns JSON, `curl_cffi` is a strong candidate for the normal PC/server HTTP transport.
- If all presets return Cloudflare HTML, protected PC/server requests need either CamoufoxTransport or manual cookies plus a compatible low-level transport.

Observed result:

```text
impersonate: chrome
status: 200
content-type: application/json; charset=utf-8
cf html: False
json posts: 3
```

Interpretation:

- Danbooru can be accessed without Camoufox when using `curl_cffi` with Chrome impersonation.
- The failure of vanilla `requests` is likely transport fingerprint related, not a missing cookie issue.
- For PC/server provider requests, a `CurlCffiTransport` is currently a better default candidate than `CamoufoxTransport`.
- Camoufox remains useful as a fallback for pages that require real browser interaction, login, or JavaScript-heavy flows.

## EH Forum Probe Result

Probe file:

```text
tmp/probes/eh_forum_challenge_probe.py
```

Target:

```text
https://forums.e-hentai.org/
```

Observed result:

- `curl_cffi` alone failed for all tested impersonations: `chrome`, `chrome124`, `safari`, `firefox`.
- Each returned Cloudflare `403 Just a moment...`.
- Camoufox visible mode displayed the Cloudflare interaction widget.
- After manually clicking the widget, Camoufox reached forum page title `E-Hentai Forums`.
- Camoufox cookies included `cf_clearance` and `ipb_session_id`.
- Importing those cookies and the browser user-agent into `curl_cffi` succeeded:

```text
curl verify status: 200
curl verify content-type: text/html
curl verify challenge markers: False
```

Interpretation:

- EH forum is a real interaction challenge case, unlike Danbooru API.
- `curl_cffi` is not enough by itself.
- Camoufox works as a PC challenge backend.
- The solved `cf_clearance` can be handed off to `curl_cffi` for subsequent lightweight requests.
- This supports the planned architecture: mobile WebView and PC Camoufox as challenge solvers, with `curl_cffi` as the normal protected transport after cookies are available.

## EH Forum Auto-Click Result

Initial selector-based attempts could not find the Turnstile checkbox directly:

```text
page.frames included https://challenges.cloudflare.com/...
page.locator("iframe").count() returned 0
frame.locator("input[type='checkbox']") did not find a usable element
```

Working approach:

```python
for frame in page.frames:
    if "challenges.cloudflare.com" in frame.url:
        element = frame.frame_element()
        box = element.bounding_box()
        click center of box
```

Observed success in both modes:

```text
python tmp/probes/eh_forum_challenge_probe.py --camoufox --humanize --disable-coop --auto-click
python tmp/probes/eh_forum_challenge_probe.py --camoufox --headless --humanize --disable-coop --auto-click
```

Both reached:

```text
page title: E-Hentai Forums
cookies: ['cf_clearance', 'ipb_session_id']
curl verify status: 200
curl verify challenge markers: False
```

Interpretation:

- We do not need to access the internal Turnstile checkbox DOM for this case.
- The cross-origin challenge frame's outer bounding box is enough.
- Camoufox headless + humanize + frame-center click can solve this EH forum challenge in the current environment.
- The implementation must still keep fallback paths because Cloudflare challenge layouts can change.

## Reusable Solver

The headless Camoufox cookie/challenge behavior was extracted to:

```text
tmp/lib/challenge/camoufox_solver.py
```

Public function:

```python
from tmp.lib.challenge import solve_with_camoufox
```

It returns:

```text
url
final_url
user_agent
cookies
html_prefix
solved
challenge_detected
cookie_names
```

Validation probes:

```powershell
python tmp/probes/camoufox_cookie_probe.py eh-forum
python tmp/probes/camoufox_cookie_probe.py danbooru
python tmp/probes/eh_forum_challenge_probe.py --camoufox --headless --humanize --disable-coop --auto-click
```

Observed results after extraction:

- EH forum: solved headlessly, got `cf_clearance` and `ipb_session_id`, `curl_cffi` verification returned `200`.
- Danbooru API URL: solved headlessly without challenge markers, got `_danbooru2_session`, returned JSON in browser body.

## Browser Cache Singleton

Experimental cache module:

```text
tmp/lib/challenge/browser_cache.py
```

Public singleton:

```python
from tmp.lib.challenge import browser_cache
```

Cache location:

```text
tmp/.cache/browser_profiles/<profile>.json
```

The cache is profile-based rather than globally shared. This matters because EH main site, EH forum, Danbooru, Gelbooru, Pixiv, and future sites can require different cookies, user-agents, and challenge state.

Current probe:

```powershell
python tmp/probes/challenge_cache_probe.py eh-forum
python tmp/probes/challenge_cache_probe.py danbooru
python tmp/probes/challenge_cache_probe.py eh-forum --force
```

Flow:

```text
load profile cache
-> verify with curl_cffi
-> if valid, reuse
-> if invalid/missing/forced, solve with Camoufox
-> save cookies + user-agent + metadata
-> verify saved cache
```

Notes:

- EH main site itself may not show CF, but EH forum does.
- EH site account cookies are handled elsewhere in the main app; EH forum challenge cookies are a separate browser-profile concern.
- For later Booru/Pixiv providers, the same cache manager can hold per-site challenge cookies.
- Cookie values are sensitive and must not be printed or committed.

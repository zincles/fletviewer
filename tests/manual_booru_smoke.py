"""Run a live, one-result search against every registered Booru provider.

This is deliberately a manual network probe, not part of unittest discovery.
"""

from __future__ import annotations

import time
from pathlib import Path
import sys

# Direct execution starts with tests/ on sys.path instead of the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.booru_session import get_booru_client
from core.provider.booru import BOORU_PROVIDER_SPECS


def main() -> int:
    failures = 0
    for provider_id, spec in BOORU_PROVIDER_SPECS.items():
        started = time.monotonic()
        try:
            client = get_booru_client(provider_id)
            result = client.search_posts("cat", limit=1)
            details = ""
            if result.posts:
                post = client.get_post(result.posts[0].id)
                details = f" detail={post.id} image={bool(post.image_url)}"
            suggestions = ""
            if spec.supports_tag_suggestions:
                tag_results = client.tag_suggestions("cat", limit=1)
                suggestions = f" tags={len(tag_results)}"
            status = f"OK posts={len(result.posts)} next={bool(result.next_page)}{details}{suggestions}"
        except Exception as ex:
            failures += 1
            status = f"{type(ex).__name__}: {ex}"
        elapsed = int((time.monotonic() - started) * 1000)
        print(f"{provider_id}\t{spec.protocol}\t{status}\t{elapsed}ms")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())

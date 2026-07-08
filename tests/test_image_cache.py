import sys

sys.path.insert(0, ".")

from app.image_cache import (
    drop_cached_filename,
    filename_for_url,
    get_gallery_page_cached_filename,
    get_cached_filename,
    path_for_filename,
    put_gallery_page_cached_filename,
    put_cached_filename,
    repair_gallery_page_entry,
    repair_stale_entry,
)
from app.image_fetcher import image_fetcher


print("=== Test 1: sharded cache path ===")
url = "https://ehgt.org/m/test.jpg"
filename = filename_for_url(url, mime="image/jpeg")
path = path_for_filename(filename)
print("filename:", filename)
print("sharded path:", path)
assert path.parts[-3] == filename[:2]
assert path.parts[-2] == filename[2:4]
assert path.name == filename

print("\n=== Test 2: stale index repair ===")
stale_url = "https://example.invalid/stale.jpg"
put_cached_filename(stale_url, filename)
print("before repair:", get_cached_filename(stale_url))
assert get_cached_filename(stale_url) == filename
assert repair_stale_entry(stale_url) is True
print("after repair:", get_cached_filename(stale_url))
assert get_cached_filename(stale_url) is None
drop_cached_filename(stale_url)

print("\n=== Test 3: gallery page cache repair ===")
put_gallery_page_cached_filename("ehentai", "123", "abc", 0, filename, kind="original")
print("page cache before repair:", get_gallery_page_cached_filename("ehentai", "123", "abc", 0))
assert get_gallery_page_cached_filename("ehentai", "123", "abc", 0) == filename
assert repair_gallery_page_entry("ehentai", "123", "abc", 0) is True
print("page cache after repair:", get_gallery_page_cached_filename("ehentai", "123", "abc", 0))
assert get_gallery_page_cached_filename("ehentai", "123", "abc", 0) is None

print("\n=== Test 4: fetch real cover via shared fetcher ===")
test_url = "https://ehgt.org/m/001135/56b51acb15/cover.jpg"  # may 404; just test plumbing
try:
    result = image_fetcher.fetch(test_url)
    print(f"fetch OK: {len(result.data)} bytes, content-type={result.mime}")
except Exception as ex:
    print(f"fetch failed (expected if URL invalid): {ex}")

print("\nAll imports OK, shared cache plumbing OK.")

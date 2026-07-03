import os
import sys
sys.path.insert(0, ".")

from app.image_proxy import public_src, _handle_thumb, start_cache_server

print("=== Test 1: public_src without FLETVIEWER_WEB set ===")
os.environ.pop("FLETVIEWER_WEB", None)
print("desktop (port=None):", public_src("https://ehgt.org/m/test.jpg"))

print("\n=== Test 2: public_src with FLETVIEWER_WEB=1 ===")
os.environ["FLETVIEWER_WEB"] = "1"
print("web:", public_src("https://ehgt.org/m/test.jpg"))

print("\n=== Test 3: start local server + fetch real cover ===")
os.environ.pop("FLETVIEWER_WEB", None)
port = start_cache_server()
print("started port:", port)
print("public_src desktop now:", public_src("https://ehgt.org/m/test.jpg"))

# Test real fetch via handler
import urllib.request
test_url = "https://ehgt.org/m/001135/56b51acb15/cover.jpg"  # may 404; just test plumbing
try:
    data, ct = _handle_thumb(test_url)
    print(f"fetch OK: {len(data)} bytes, content-type={ct}")
except Exception as ex:
    print(f"fetch failed (expected if URL invalid): {ex}")
print("\nAll imports OK, server started OK.")
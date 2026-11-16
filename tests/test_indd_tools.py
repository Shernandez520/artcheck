"""Unit tests for indd_tools.py (no browser, no Streamlit, no InDesign file needed).

    python tests/test_indd_tools.py

The sample comes from make_fixtures.fake_indd(), which lays XMP packets out the way
real InDesign documents do. The reader was also checked by hand against three real
documents (InDesign CC 2017 on Mac, InDesign 18 on Windows; 2.5 to 26 MB).
"""
import io
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import indd_tools  # noqa: E402
from make_fixtures import fake_indd, INDD_MAGIC, _xmp_packet  # noqa: E402

PASSED = 0


def check(name, condition, detail=""):
    global PASSED
    if not condition:
        print(f"❌ {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✅ {name}")


def center(result):
    return Image.open(io.BytesIO(result["image"])).convert("RGB").getpixel((result["width"] // 2, result["height"] // 2))


doc = fake_indd()
found = indd_tools.thumbnail(doc)
check("thumbnail is found in an InDesign document", found is not None)
check("thumbnail size is reported", (found["width"], found["height"]) == (256, 198), str(found and (found["width"], found["height"])))
r, g, b = center(found)
check("the newest InDesign save wins over older saves and placed images", b > 150 and r < 90, f"center pixel {(r, g, b)}")
check("the app and save date are reported", found["app"] == "Adobe InDesign 18.4 (Windows)" and found["saved"] == "2025-05-09",
      f"{found['app']} {found['saved']}")

check("a document saved without previews gives nothing", indd_tools.thumbnail(fake_indd(with_thumbnail=False)) is None)
check("a file that is not InDesign gives nothing", indd_tools.thumbnail(b"not a real InDesign file") is None)
check("a renamed file with a thumbnail but no InDesign signature gives nothing", indd_tools.thumbnail(doc[16:]) is None)

# newest preview unreadable (InDesign stores long metadata in pieces): fall back to the older one
broken = _xmp_packet("Adobe InDesign 19.0 (Windows)", "2026-01-01T00:00:00Z", (0, 200, 0))
broken = broken.replace(b"<xmpGImg:image>", b"<xmpGImg:image>AAAA")
older = indd_tools.thumbnail(INDD_MAGIC + broken + doc[16:])
check("an unreadable newest preview falls back to the previous save",
      older is not None and older["saved"] == "2025-05-09", str(older and older["saved"]))

print(f"\n{PASSED} checks passed")

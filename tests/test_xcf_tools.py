"""Unit tests for xcf_tools.py (no browser, no Streamlit, no GIMP needed).

    python tests/test_xcf_tools.py

tests/data/xcf holds small files saved by GIMP 2.10.36 from generated shapes
(make_samples.scm is the Script-Fu that made them) and, next to each, the PNG that
GIMP itself exported from the same image. The reader must reproduce GIMP's picture.
It was also checked by hand against two real GIMP projects (5 layers at 1920 x 1080
and 43 layers at 3840 x 4320): no pixel more than 1 level away from GIMP's export.
"""
import os
import sys

from PIL import Image, ImageChops, ImageStat

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import xcf_tools  # noqa: E402

DATA = os.path.join(HERE, "data", "xcf")
PASSED = 0


def check(name, condition, detail=""):
    global PASSED
    if not condition:
        print(f"❌ {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✅ {name}")


def load(name):
    with open(os.path.join(DATA, name + ".xcf"), "rb") as fh:
        return fh.read()


def difference(name, linear_reference=False):
    """(mean, max) difference from GIMP's own export, compared on white."""
    mine = xcf_tools.flatten(load(name))["image"]
    ref = Image.open(os.path.join(DATA, name + ".gimp.png")).convert("RGBA")
    if linear_reference:      # GIMP exports linear-light images as linear PNGs
        lut = xcf_tools._srgb_lut()
        r, g, b, a = ref.split()
        ref = Image.merge("RGBA", (r.point(lut), g.point(lut), b.point(lut), a))
    flat = []
    for img in (mine, ref):
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        white.alpha_composite(img)
        flat.append(white.convert("RGB"))
    diff = ImageChops.difference(*flat)
    return sum(ImageStat.Stat(diff).mean) / 3, max(high for _, high in diff.getextrema())


plain = xcf_tools.flatten(load("plain"))
check("size, resolution and layer counts are read",
      (plain["width"], plain["height"], plain["layers"], plain["hidden"]) == (300, 200, 3, 1)
      and round(plain["dpi"][0]) == 300, str({k: v for k, v in plain.items() if k != "image"}))
check("result is a transparent-capable image of the canvas size",
      plain["image"].mode == "RGBA" and plain["image"].size == (300, 200))
check("hidden layer is left out (it is solid green)", plain["image"].getpixel((5, 195))[1] < 250)
check("describe() agrees without decoding pixels",
      xcf_tools.describe(load("plain"))["width"] == 300 and xcf_tools.describe(load("plain"))["layers"] == 4)

CASES = [
    ("plain", "layers with offsets, opacity and soft edges (GIMP 2.10 Normal, linear light)", False, 2),
    ("mask", "layer mask", False, 2),
    ("multiply_new", "Multiply blend mode (GIMP 2.10)", False, 2),
    ("group_mult", "layer group with a mask and a Multiply layer inside", False, 2),
    ("group_pass", "pass-through layer group", False, 2),
    ("gray", "grayscale image", False, 2),
    ("u16lin", "16-bit linear-light image", True, 12),
]
for name, label, linear, limit in CASES:
    mean, worst = difference(name, linear)
    check(f"matches GIMP's own export: {label}", mean < 2.0 and worst <= limit, f"mean {mean:.2f}, max {worst}")

for bad, label in ((b"gimp xcf file\x00not a real GIMP file", "damaged file"),
                   (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "file that is not GIMP"),
                   (load("plain")[:900], "file cut short")):
    try:
        xcf_tools.flatten(bad)
        check(f"{label} is refused with a message", False, "no error raised")
    except xcf_tools.XcfError as err:
        check(f"{label} is refused with a message", len(str(err)) > 10)

try:
    xcf_tools.flatten(load("plain"), max_pixels=1000)
    check("oversized canvas is refused before any pixels are read", False)
except xcf_tools.XcfError as err:
    check("oversized canvas is refused before any pixels are read", "too large" in str(err))

print(f"\n{PASSED} checks passed")

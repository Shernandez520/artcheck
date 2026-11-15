"""Create the small sample art files the browser test uploads.

Usage: python tests/make_fixtures.py <output_dir>

Everything is generated from code so no customer artwork lives in the repo.
"""
import sys
from pathlib import Path

import pyembroidery
from PIL import Image, ImageDraw
from reportlab.lib.colors import CMYKColor, Color
from reportlab.pdfgen import canvas

RED = CMYKColor(0, 1, 1, 0)
BLUE = CMYKColor(1, 0.6, 0, 0)
BLACK = CMYKColor(0, 0, 0, 1)


def vector_pdf(path, width_pt, height_pt, color):
    """A vector logo: a colored panel, a black circle and two small squares."""
    c = canvas.Canvas(str(path), pagesize=(width_pt, height_pt))
    c.setFillColor(color)
    c.rect(width_pt * 0.1, height_pt * 0.1, width_pt * 0.8, height_pt * 0.8, fill=1, stroke=0)
    c.setFillColor(BLACK)
    c.circle(width_pt / 2, height_pt / 2, min(width_pt, height_pt) * 0.2, fill=1, stroke=0)
    c.rect(width_pt * 0.2, height_pt * 0.2, 10, 10, fill=1, stroke=0)
    c.rect(width_pt * 0.3, height_pt * 0.2, 10, 10, fill=1, stroke=0)
    c.save()


def white_logo_pdf(path):
    """White artwork on a transparent 3" x 2" page (the white-on-white case)."""
    c = canvas.Canvas(str(path), pagesize=(216, 144))
    c.setFillColor(Color(1, 1, 1))
    c.circle(108, 72, 43, fill=1, stroke=0)
    for x in (10, 50, 90):
        c.rect(x, 10, 30, 12, fill=1, stroke=0)
    c.save()


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    vector_pdf(out / "logo_red_3x2in.pdf", 216, 144, RED)      # 3" x 2"
    vector_pdf(out / "logo_blue_3x2in.pdf", 216, 144, BLUE)    # 3" x 2"
    vector_pdf(out / "letter_page.pdf", 612, 792, RED)         # 8.5" x 11"
    white_logo_pdf(out / "white_logo.pdf")

    (out / "logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" viewBox="0 0 300 200">'
        '<rect x="20" y="20" width="260" height="160" fill="#008800"/>'
        '<circle cx="150" cy="100" r="50" fill="#ffffff"/></svg>'
    )

    # Same artwork, but the SVG states a real-world size: 3in x 2in
    (out / "logo_3x2in.svg").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<!-- stroke-width="9in" in a comment must not be read as the size -->\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="3in" height="50.8mm" viewBox="0 0 300 200">'
        '<rect x="20" y="20" width="260" height="160" fill="#008800"/></svg>'
    )

    # Two-page PDF (page 1 is 3" x 2")
    c = canvas.Canvas(str(out / "two_pages.pdf"), pagesize=(216, 144))
    for color in (RED, BLUE):
        c.setFillColor(color)
        c.rect(20, 20, 176, 104, fill=1, stroke=0)
        c.setFillColor(BLACK)
        c.rect(30, 30, 10, 10, fill=1, stroke=0)
        c.rect(50, 30, 10, 10, fill=1, stroke=0)
        c.circle(108, 72, 20, fill=1, stroke=0)
        c.showPage()
    c.save()

    # 3" x 2" EPS with CMYK fills (rendered by Ghostscript in production)
    (out / "logo_3x2in.eps").write_text(
        "%!PS-Adobe-3.0 EPSF-3.0\n"
        "%%BoundingBox: 0 0 216 144\n"
        "%%EndComments\n"
        "0 1 1 0 setcmykcolor\n"
        "20 20 176 104 rectfill\n"
        "0 0 0 1 setcmykcolor\n"
        "newpath 108 72 30 0 360 arc closepath fill\n"
        "showpage\n"
        "%%EOF\n"
    )

    # 900 x 600 px image tagged 72 DPI: enough pixels for "borderline", not "good"
    photo = Image.new("RGB", (900, 600), "white")
    ImageDraw.Draw(photo).ellipse([100, 100, 800, 500], fill=(200, 0, 200))
    photo.save(out / "photo_900x600.png", dpi=(72, 72))

    # A PDF that is only a picture (the "raster saved as vector" case)
    c = canvas.Canvas(str(out / "raster_in.pdf"), pagesize=(300, 200))
    c.drawImage(str(out / "photo_900x600.png"), 0, 0, 300, 200)
    c.save()

    # 200-stitch embroidery file, 19 mm x 9 mm
    pattern = pyembroidery.EmbPattern()
    pattern.add_thread({"color": 0xFF0000})
    for i in range(200):
        pattern.add_stitch_absolute(pyembroidery.STITCH, (i % 20) * 10, (i // 20) * 10)
    pattern.end()
    pyembroidery.write_dst(pattern, str(out / "stitch.dst"))

    # InDesign is unsupported; the app only looks at the file name
    (out / "layout.indd").write_bytes(b"not a real InDesign file")

    print(f"Created {len(list(out.iterdir()))} sample files in {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures")

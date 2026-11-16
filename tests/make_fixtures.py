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


INDD_MAGIC = bytes.fromhex("0606edf5d81d46e5bd31efe7fe74b71d")


def _xmp_packet(creator, saved, thumb_color=None, size=(256, 198)):
    """One XMP packet the way Adobe apps write it, optionally with a JPEG thumbnail."""
    import base64
    import io
    thumbs = ""
    if thumb_color:
        img = Image.new("RGB", size, "white")
        ImageDraw.Draw(img).rectangle([40, 40, size[0] - 40, size[1] - 40], fill=thumb_color)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode()
        b64 = "&#xA;".join(b64[i:i + 76] for i in range(0, len(b64), 76))
        thumbs = (f"<xmp:Thumbnails><rdf:Alt><rdf:li rdf:parseType=\"Resource\">"
                  f"<xmpGImg:format>JPEG</xmpGImg:format><xmpGImg:width>{size[0]}</xmpGImg:width>"
                  f"<xmpGImg:height>{size[1]}</xmpGImg:height><xmpGImg:image>{b64}</xmpGImg:image>"
                  f"</rdf:li></rdf:Alt></xmp:Thumbnails>")
    return (f"<?xpacket begin=\"\ufeff\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n<x:xmpmeta xmlns:x=\"adobe:ns:meta/\">"
            f"<rdf:RDF><rdf:Description><xmp:CreatorTool>{creator}</xmp:CreatorTool>"
            f"<xmp:MetadataDate>{saved}</xmp:MetadataDate>{thumbs}</rdf:Description></rdf:RDF></x:xmpmeta>\n"
            f"<?xpacket end=\"r\"?>").encode("utf-8")


def fake_indd(with_thumbnail=True):
    """Bytes laid out like an InDesign document as far as ArtCheck reads it: the file
    signature, binary filler, and XMP packets. Like a real one it holds a placed
    Photoshop image's packet (with its own thumbnail), an older save of the document
    and the newest save. The newest thumbnail is blue, the others red and gray."""
    filler = bytes(range(256)) * 16
    parts = [INDD_MAGIC, filler,
             _xmp_packet("Adobe Photoshop 24.2 (Windows)", "2025-06-01T10:00:00-04:00", (200, 30, 40)), filler,
             _xmp_packet("Adobe InDesign 18.2 (Windows)", "2025-03-01T09:00:00-04:00",
                         (120, 120, 120) if with_thumbnail else None), filler,
             _xmp_packet("Adobe InDesign 18.4 (Windows)", "2025-05-09T17:47:39-04:00",
                         (30, 80, 210) if with_thumbnail else None), filler]
    return b"".join(parts)


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 900 x 600 px image tagged 72 DPI: enough pixels for "borderline", not "good"
    photo = Image.new("RGB", (900, 600), "white")
    ImageDraw.Draw(photo).ellipse([100, 100, 800, 500], fill=(200, 0, 200))
    photo.save(out / "photo_900x600.png", dpi=(72, 72))

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

    # Seven different CMYK colors (triggers the many-colors warning).
    # None is a pure 100% C, M, Y or K: ColorExtractor skips those as registration artifacts.
    c = canvas.Canvas(str(out / "seven_colors.pdf"), pagesize=(216, 144))
    for i, cmyk in enumerate([(0, 1, 1, 0), (1, 0.6, 0, 0), (0, 0.2, 1, 0), (1, 0, 1, 0), (0, 0.5, 1, 0), (0.5, 1, 0, 0), (0, 0, 0, 0.8)]):
        c.setFillColor(CMYKColor(*cmyk))
        c.rect(10 + i * 28, 20, 24, 104, fill=1, stroke=0)
    c.save()

    # Pure 100% inks: black, yellow and red (M+Y) are painted and must be listed.
    # Cyan and magenta are only *set*, never painted, and must NOT be listed.
    c = canvas.Canvas(str(out / "pure_inks.pdf"), pagesize=(216, 144))
    c.setFillColor(CMYKColor(1, 0, 0, 0))            # set, never used
    c.setFillColor(CMYKColor(0, 0, 0, 1))
    c.rect(10, 20, 60, 104, fill=1, stroke=0)        # pure black
    c.saveState()
    c.setFillColor(CMYKColor(0, 1, 0, 0))            # set inside a saved state, never used
    c.restoreState()
    c.rect(78, 20, 10, 104, fill=1, stroke=0)        # still black after restore
    c.setFillColor(CMYKColor(0, 0, 1, 0))
    c.rect(96, 20, 50, 104, fill=1, stroke=0)        # pure yellow
    c.setFillColor(CMYKColor(0, 1, 1, 0))
    c.rect(154, 20, 50, 104, fill=1, stroke=0)       # red
    c.save()

    # Illustrator files saved with PDF compatibility are PDFs inside
    vector_pdf(out / "logo_3x2in.ai", 216, 144, BLUE)

    # Illustrator-style EPS headers. Illustrator declares its inks in the header and
    # ALSO has the word "Separation" all through its boilerplate, which must not be
    # read as a spot color.
    boilerplate = "".join(f"% procset note {i}: /Separation and DeviceN handling\n" for i in range(5))
    (out / "illustrator_style_black.eps").write_text(
        "%!PS-Adobe-3.1 EPSF-3.0\n"
        "%%BoundingBox: 0 0 216 144\n"
        "%%DocumentProcessColors:  Black\n"
        "%%DocumentCustomColors: \n"
        "%%CMYKCustomColor: \n"
        "%%EndComments\n" + boilerplate +
        "0 0 0 1 setcmykcolor\n"
        "20 20 176 104 rectfill\n"
        "showpage\n"
        "%%EOF\n"
    )
    (out / "illustrator_style_spot.eps").write_text(
        "%!PS-Adobe-3.1 EPSF-3.0\n"
        "%%BoundingBox: 0 0 216 144\n"
        "%%DocumentProcessColors:  Black\n"
        "%%DocumentCustomColors: (PANTONE 186 C)\n"
        "%%+ (Brand Blue)\n"
        "%%CMYKCustomColor: 0 1 0.81 0.04 (PANTONE 186 C)\n"
        "%%+ 1 0.6 0 0 (Brand Blue)\n"
        "%%EndComments\n" + boilerplate +
        "[/Separation (PANTONE 186 C) /DeviceCMYK {dup 0 mul exch dup 1 mul exch dup 0.81 mul exch 0.04 mul}] setcolorspace\n"
        "1 setcolor\n"
        "20 20 80 104 rectfill\n"
        "[/Separation (Brand Blue) /DeviceCMYK {dup 1 mul exch dup 0.6 mul exch dup 0 mul exch 0 mul}] setcolorspace\n"
        "1 setcolor\n"
        "110 20 80 104 rectfill\n"
        "0 0 0 1 setcmykcolor\n"
        "20 130 170 6 rectfill\n"
        "showpage\n"
        "%%EOF\n"
    )

    # EPS with a Pantone spot color
    (out / "spot_logo.eps").write_text(
        "%!PS-Adobe-3.0 EPSF-3.0\n"
        "%%BoundingBox: 0 0 216 144\n"
        "%%EndComments\n"
        "[/Separation (PANTONE 186 C) /DeviceCMYK {dup 0 mul exch dup 1 mul exch dup 0.81 mul exch 0.04 mul}] setcolorspace\n"
        "1 setcolor\n"
        "20 20 176 104 rectfill\n"
        "showpage\n"
        "%%EOF\n"
    )

    # SVG that is mostly a picture: one embedded PNG plus one vector rectangle
    import base64, io
    dot = Image.new("RGB", (40, 40), (200, 0, 0))
    buf = io.BytesIO()
    dot.save(buf, format="PNG")
    (out / "picture_in.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="3in" height="2in" viewBox="0 0 300 200">'
        '<rect x="10" y="10" width="80" height="60" fill="#008800"/>'
        f'<image x="100" y="20" width="160" height="160" xlink:href="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"/>'
        '</svg>'
    )

    # Two-page PDF: page 1 is 3" x 2" and red, page 2 is 5" x 4" and blue
    def two_pages(path):
        c = canvas.Canvas(str(path), pagesize=(216, 144))
        for (w, h), color in (((216, 144), RED), ((360, 288), BLUE)):
            c.setPageSize((w, h))
            c.setFillColor(color)
            c.rect(20, 20, w - 40, h - 40, fill=1, stroke=0)
            c.setFillColor(BLACK)
            c.rect(30, 30, 10, 10, fill=1, stroke=0)
            c.rect(50, 30, 10, 10, fill=1, stroke=0)
            c.circle(w / 2, h / 2, 20, fill=1, stroke=0)
            c.showPage()
        c.save()
    two_pages(out / "two_pages.pdf")
    two_pages(out / "two_artboards.ai")   # multi-artboard Illustrator files are multi-page PDFs inside

    # Page 1 is only a picture (a scan), page 2 is real vector art
    c = canvas.Canvas(str(out / "scan_then_vector.pdf"), pagesize=(300, 200))
    c.drawImage(str(out / "photo_900x600.png"), 0, 0, 300, 200)
    c.showPage()
    c.setFillColor(BLUE)
    c.rect(20, 20, 260, 160, fill=1, stroke=0)
    c.setFillColor(BLACK)
    c.rect(30, 30, 10, 10, fill=1, stroke=0)
    c.rect(50, 30, 10, 10, fill=1, stroke=0)
    c.circle(150, 100, 20, fill=1, stroke=0)
    c.save()

    # Live (non-outlined) text: Helvetica is NOT embedded, Vera IS embedded
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pdfmetrics.registerFont(TTFont("Vera", "Vera.ttf"))  # ships with reportlab
    c = canvas.Canvas(str(out / "live_text.pdf"), pagesize=(216, 144))
    c.setFillColor(RED)
    c.rect(20, 80, 176, 44, fill=1, stroke=0)
    c.setFillColor(BLACK)
    c.setFont("Helvetica", 18)
    c.drawString(20, 50, "Acme Plumbing")
    c.setFont("Vera", 10)
    c.drawString(20, 30, "Since 1987")
    c.save()

    (out / "live_text.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="3in" height="2in" viewBox="0 0 300 200">'
        '<rect x="20" y="20" width="260" height="80" fill="#008800"/>'
        '<text x="20" y="150" font-family="Georgia, serif" font-size="32">Acme Plumbing</text></svg>'
    )

    (out / "live_text.eps").write_text(
        "%!PS-Adobe-3.0 EPSF-3.0\n"
        "%%BoundingBox: 0 0 216 144\n"
        "%%DocumentFonts: Helvetica\n"
        "%%EndComments\n"
        "0 1 1 0 setcmykcolor\n"
        "20 80 176 44 rectfill\n"
        "0 0 0 1 setcmykcolor\n"
        "/Helvetica findfont 18 scalefont setfont\n"
        "20 50 moveto (Acme Plumbing) show\n"
        "showpage\n"
        "%%EOF\n"
    )

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

    # Large logo that fades out to transparent (not allowed for DTFx / stickers)
    fade = Image.new("RGBA", (1500, 1500), (0, 0, 0, 0))
    for y in range(1500):
        ImageDraw.Draw(fade).line([(200, y), (1300, y)], fill=(0, 90, 200, int(255 * y / 1499)))
    fade.save(out / "fade_1500px.png", dpi=(300, 300))

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

    # InDesign: one file with the page thumbnail InDesign normally saves, one without
    (out / "layout.indd").write_bytes(fake_indd())
    (out / "no_preview.indd").write_bytes(b"not a real InDesign file")
    # GIMP: a real file made by GIMP 2.10 from generated shapes (see tests/data/xcf),
    # and one that is damaged
    here = Path(__file__).resolve().parent
    (out / "artwork.xcf").write_bytes((here / "data" / "xcf" / "plain.xcf").read_bytes())
    (out / "damaged.xcf").write_bytes(b"gimp xcf file\x00not a real GIMP file")

    print(f"Created {len(list(out.iterdir()))} sample files in {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures")

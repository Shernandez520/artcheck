"""Browser test for ArtCheck.

Opens the running app in a real (headless) browser, uploads sample files the
way a sales rep would, and checks what the page shows.

    python tests/make_fixtures.py /tmp/artcheck-fixtures
    python tests/e2e_test.py --url http://localhost:8501 --fixtures /tmp/artcheck-fixtures

Exits 0 when every check passes and 1 when any check fails.
Set SKIP_EPS=1 on machines without Ghostscript.
Google Analytics requests are blocked so test runs never reach real analytics.
"""
import argparse
import base64
import io
import os
import re
import sys
import traceback

from PIL import Image
from playwright.sync_api import sync_playwright

RESULTS = []  # (name, passed, detail)


def metrics(page):
    """All st.metric tiles on the page as {label: value}."""
    out = {}
    for tile in page.locator('[data-testid="stMetric"]').all():
        label = tile.locator('[data-testid="stMetricLabel"]').inner_text().strip()
        out[label] = tile.locator('[data-testid="stMetricValue"]').inner_text().strip()
    return out


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


class App:
    def __init__(self, context, url, fixtures, shots):
        self.context, self.url, self.fixtures, self.shots = context, url.rstrip("/"), fixtures, shots
        self.page = None

    def fresh(self):
        """New browser tab = new, empty ArtCheck session."""
        if self.page:
            self.page.close()
        self.page = self.context.new_page()
        self.page.goto(self.url + "/")
        self.page.get_by_text("Upload Your File").wait_for(timeout=90_000)
        # The sidebar is drawn last, so once it is there the whole page has rendered
        self.page.locator("input[type=file]").wait_for(state="attached", timeout=60_000)
        self.wait_for_sidebar()
        return self.page

    def wait_for_sidebar(self):
        """ArtBot's sidebar (not the words 'Ask ArtBot' in the intro paragraph)."""
        self.page.locator('[data-testid="stSidebar"]').get_by_text("Ask ArtBot").first.wait_for(timeout=60_000)

    def upload(self, name):
        self.page.locator("input[type=file]").set_input_files(os.path.join(self.fixtures, name))

    def upload_vector(self, name):
        self.upload(name)
        self.page.get_by_text("Uploaded:").wait_for(timeout=30_000)

    def generate(self):
        self.page.get_by_role("button", name="🚀 Generate Preview").click()
        self.page.get_by_text("Preview generated successfully").wait_for(timeout=120_000)
        self.page.wait_for_timeout(1500)

    def no_errors(self):
        count = self.page.locator('[data-testid="stException"]').count()
        expect(count == 0, f"the page shows {count} error box(es)")

    def preview_png(self):
        """The preview image shown in the pan/zoom viewer."""
        for frame in self.page.frames:
            img = frame.locator("#img")
            if img.count():
                src = img.first.get_attribute("src")
                return base64.b64decode(src.split("base64,", 1)[1])
        raise AssertionError("preview image not found on the page")

    def mockup_artwork_color(self):
        """Open the Mockup Builder link and report the main color of the art it was handed."""
        href = self.page.locator('a:has-text("Open Mockup Builder")').first.get_attribute("href")
        tab = self.context.new_page()
        tab.goto(f"{self.url}/{href}")
        tab.wait_for_timeout(4000)
        html = tab.content()
        for frame in tab.frames:
            try:
                html += frame.content()
            except Exception:
                pass
        tab.close()
        found = re.search(r'__preloadedArtwork = (?:&quot;|")data:image/png;base64,([A-Za-z0-9+/=]+)', html)
        expect(found, "Mockup Builder opened without any preloaded artwork")
        img = Image.open(io.BytesIO(base64.b64decode(found.group(1)))).convert("RGBA")
        img.thumbnail((60, 60))
        px = [p for p in img.getdata() if p[3] > 200 and p[:3] != (0, 0, 0)]
        r, g, b = (sum(p[i] for p in px) / len(px) for i in range(3))
        return "red" if r > b and r > g else ("blue" if b > r and b > g else "other")


# ---------------------------------------------------------------- checks

def check_home(app):
    page = app.fresh()
    app.wait_for_sidebar()
    expect(page.locator("input[type=file]").count() == 1, "file uploader is missing")
    body = page.locator('[data-testid="stMain"]').inner_text()
    expect("Supported:" not in body, "the separate 'Supported:' box is back; the uploader already lists the file types")
    expect("PDF" in body and "DST" in body and "PNG" in body, "the uploader no longer lists the accepted file types")
    expect("GIMP (.xcf) files are flattened to one image. InDesign (.indd) files show a small thumbnail only." in body,
           "the note about what GIMP and InDesign uploads get is missing")
    expect("upload them" not in body.lower(), "the page should not invite users to upload unsupported files")
    app.no_errors()


def check_vector_pdf(app):
    page = app.fresh()
    app.upload_vector("logo_red_3x2in.pdf")
    app.generate()
    m = metrics(page)
    expect(m.get("Size (inches)") == '3.0" x 2.0"', f"expected 3.0\" x 2.0\", page shows {m.get('Size (inches)')}")
    expect(m.get("File Type") == "Vector (PDF)", f"File Type shows {m.get('File Type')}")
    uploaded_kb = round(os.path.getsize(os.path.join(app.fixtures, "logo_red_3x2in.pdf")) / 1024, 2)
    expect(m.get("File Size") == f"{uploaded_kb} KB", f"File Size shows {m.get('File Size')}, the uploaded file is {uploaded_kb} KB")
    expect(page.get_by_text("ArtCheck previews and analyzes").count() == 0, "single-page PDF shows the multi-page notice")
    expect(page.get_by_text("Color Analysis").count() > 0, "Color Analysis section is missing")
    expect(page.get_by_text("Document Color Mode: CMYK").count() > 0, "CMYK document was not reported as CMYK")
    expect(page.get_by_text("No live text found").count() > 0, "file without text did not pass the Font Check")
    expect(page.get_by_role("button", name="Download PNG").count() > 0, "Download PNG button is missing")
    app.no_errors()


def check_mockup_after_switch(app):
    page = app.fresh()
    app.upload_vector("logo_red_3x2in.pdf")
    app.generate()
    page.get_by_role("button", name="🔄 New File").click()
    page.wait_for_timeout(1500)
    app.upload_vector("logo_blue_3x2in.pdf")
    app.generate()
    color = app.mockup_artwork_color()
    expect(color == "blue", f"Mockup Builder received the {color} artwork instead of the blue file just analyzed")
    app.no_errors()


def check_svg(app):
    page = app.fresh()
    app.upload_vector("logo.svg")
    app.generate()
    m = metrics(page)
    expect(m.get("Dimensions (px)") == "1200 × 800", f"dimensions show {m.get('Dimensions (px)')}")
    # This SVG has no real-world units, so there is no print size to report
    expect(m.get("Size (inches)") == "Scalable", f"Size (inches) shows {m.get('Size (inches)')}")
    app.no_errors()


def check_svg_with_units(app):
    page = app.fresh()
    app.upload_vector("logo_3x2in.svg")
    app.generate()
    m = metrics(page)
    expect(m.get("Size (inches)") == '3.0" x 2.0"', f"expected 3.0\" x 2.0\", page shows {m.get('Size (inches)')}")
    app.no_errors()


def wait_for_metric(page, label, value, timeout_s=90):
    """Wait until a Preview Info tile shows the expected value (used after auto-regeneration)."""
    for _ in range(timeout_s * 2):
        if metrics(page).get(label) == value:
            return
        page.wait_for_timeout(500)
    raise AssertionError(f"{label} never became {value}; it shows {metrics(page).get(label)}")


def check_multi_page_pdf(app):
    page = app.fresh()
    app.upload_vector("two_pages.pdf")
    app.generate()
    expect(page.get_by_text("This file has 2 pages").count() > 0, "no notice that the PDF has 2 pages")
    expect(page.get_by_text("Showing page 1").count() > 0, "the notice does not say which page is shown")
    expect(metrics(page).get("Size (inches)") == '3.0" x 2.0"', f"page 1 size shows {metrics(page).get('Size (inches)')}")
    colors = page.locator('[data-testid="stMain"]').inner_text().split("Color Analysis", 1)[1]
    expect("C:0% M:100% Y:100% K:0%" in colors, "page 1 is red, but red is not listed")

    # Pick page 2: the preview regenerates by itself, for that page only
    pick(page, "Page", "Page 2 of 2")
    wait_for_metric(page, "Size (inches)", '5.0" x 4.0"')
    body = page.locator('[data-testid="stMain"]').inner_text()
    expect("Showing page 2" in body, "the notice does not say page 2 is shown")
    colors = body.split("Color Analysis", 1)[1]
    expect("C:100% M:60% Y:0% K:0%" in colors, "page 2 is blue, but blue is not listed")
    expect("C:0% M:100% Y:100% K:0%" not in colors, "page 1's red is listed while page 2 is shown")
    pick(page, "Decoration method", "Screen Print")
    expect("Only page 2 of 2 was screened" in decoration_text(page), "the method check does not say which page it screened")

    # ...and back to page 1
    pick(page, "Page", "Page 1 of 2")
    wait_for_metric(page, "Size (inches)", '3.0" x 2.0"')
    app.no_errors()


def check_page_picker_reaches_vector_page(app):
    """Page 1 is a scan. The picker must still be usable so page 2 (vector) can be analyzed."""
    page = app.fresh()
    app.upload("scan_then_vector.pdf")
    page.get_by_text("Raster image detected inside PDF").wait_for(timeout=30_000)
    pick(page, "Page", "Page 2 of 2")
    page.wait_for_timeout(1500)
    expect(page.get_by_text("Raster image detected inside PDF").count() == 0, "page 2 is vector but is still treated as a picture")
    app.generate()
    m = metrics(page)
    expect("Vector" in m.get("File Type", ""), f"File Type shows {m.get('File Type')}")
    expect(page.get_by_text("Showing page 2").count() > 0, "the notice does not say page 2 is shown")
    app.no_errors()


def check_instant_background(app):
    page = app.fresh()
    app.upload_vector("logo_red_3x2in.pdf")
    app.generate()

    def corner():
        return Image.open(io.BytesIO(app.preview_png())).convert("RGB").getpixel((2, 2))

    def click_background(label, want, describe):
        page.get_by_role("button", name=label).click()
        for _ in range(16):      # 8 seconds at most: no Generate Preview click, no re-render
            page.wait_for_timeout(500)
            try:
                if want(corner()):
                    return
            except Exception:
                pass
        raise AssertionError(f"{label}: the preview did not switch to {describe} on its own (corner pixel {corner()})")

    expect(min(corner()) > 240, f"Auto on a red logo should start on white, got {corner()}")
    click_background("🌙 Dark", lambda c: max(c) < 60, "a dark background")
    click_background("⬜ Transparent", lambda c: c in ((204, 204, 204), (153, 153, 153)), "the checkerboard")
    click_background("☀️ Light", lambda c: min(c) > 240, "a white background")
    expect(page.get_by_text("click Generate Preview to apply").count() == 0, "the old 'click Generate Preview to apply' hint is still shown")
    app.no_errors()


def check_eps(app):
    page = app.fresh()
    app.upload_vector("logo_3x2in.eps")
    app.generate()
    m = metrics(page)
    expect(m.get("Size (inches)") == '3.0" x 2.0"', f"expected 3.0\" x 2.0\", page shows {m.get('Size (inches)')}")
    expect(page.get_by_text("Color Analysis").count() > 0, "Color Analysis section is missing")
    expect(page.get_by_text("No live text found").count() > 0, "EPS without text did not pass the Font Check")
    colors = page.locator('[data-testid="stMain"]').inner_text().split("Color Analysis", 1)[1]
    expect("K:100%" in colors, "the EPS has a pure black shape, but black is not listed in Color Analysis")
    expect("C:0% M:100% Y:100% K:0%" in colors, "the EPS has a red shape, but red is not listed in Color Analysis")
    app.no_errors()


def check_eps_color_mode_from_header(app):
    """Illustrator EPS files say 'Separation' throughout their boilerplate. That is not a spot color."""
    page = app.fresh()
    app.upload_vector("illustrator_style_black.eps")
    app.generate()
    body = page.locator('[data-testid="stMain"]').inner_text()
    expect("Document Color Mode: CMYK" in body, "a black-only EPS should be reported as CMYK")
    expect("Spot" not in body.split("Color Analysis", 1)[1], "a black-only EPS is reported as having a spot color")
    expect("K:100%" in body, "black is not listed")
    expect(metrics(page).get("File Type") == "Vector (EPS)", f"File Type shows {metrics(page).get('File Type')}")

    page = app.fresh()
    app.upload_vector("illustrator_style_spot.eps")
    app.generate()
    colors = page.locator('[data-testid="stMain"]').inner_text().split("Color Analysis", 1)[1]
    expect("Document Color Mode: Spot + CMYK" in colors, "an EPS with spot colors and black should be Spot + CMYK")
    expect("PANTONE 186 C" in colors, "the Pantone spot color is not listed")
    expect("Brand Blue" in colors, "the custom-named spot color is not listed")
    app.no_errors()


def font_check_text(page):
    """Everything shown from the Font Check heading down."""
    body = page.locator('[data-testid="stMain"]').inner_text()
    expect("Font Check" in body, "Font Check section is missing")
    return body.split("Font Check", 1)[1]


def check_fonts_pdf(app):
    page = app.fresh()
    app.upload_vector("live_text.pdf")
    app.generate()
    text = font_check_text(page)
    expect("Live text found" in text, "live text in the PDF was not flagged")
    expect("Helvetica (not embedded)" in text, "Helvetica should be listed as not embedded")
    expect("BitstreamVeraSans-Roman (embedded)" in text, "Vera should be listed as embedded")
    expect("Acme Plumbing" in text, "the text that was found is not shown")
    expect("What to tell your customer" in text, "customer script is missing")
    app.no_errors()


def check_fonts_svg(app):
    page = app.fresh()
    app.upload_vector("live_text.svg")
    app.generate()
    text = font_check_text(page)
    expect("Live text found" in text, "live text in the SVG was not flagged")
    expect("Georgia" in text, "font name Georgia is not listed")
    app.no_errors()


def check_fonts_eps(app):
    page = app.fresh()
    app.upload_vector("live_text.eps")
    app.generate()
    text = font_check_text(page)
    expect("Live text found" in text, "live text in the EPS was not flagged")
    expect("Helvetica" in text, "font name Helvetica is not listed")
    app.no_errors()


def check_embroidery(app):
    page = app.fresh()
    app.upload_vector("stitch.dst")
    app.generate()
    m = metrics(page)
    expect(m.get("Stitch Count") == "200", f"Stitch Count shows {m.get('Stitch Count')}")
    expect(m.get("Size (inches)") == '0.75" x 0.35"', f"Size (inches) shows {m.get('Size (inches)')}")
    app.no_errors()


def check_raster_png(app):
    page = app.fresh()
    app.upload("photo_900x600.png")
    page.get_by_text("Usable Print Sizes").wait_for(timeout=30_000)
    expect(page.get_by_text("Borderline Quality").count() > 0, "900x600 @72dpi image was not rated Borderline")
    expect(metrics(page).get("Dimensions") == "900 × 600 px", f"Dimensions show {metrics(page).get('Dimensions')}")
    body = page.locator('[data-testid="stMain"]').inner_text()
    # The print-size table must agree with the Decoration Method Check: 200 dpi is the minimum
    expect("DTG only" not in body and "150" not in body.split("Usable Print Sizes", 1)[1].split("Decoration Method Check", 1)[0],
           "the print-size table still lists 150 dpi as usable")
    expect('4.5" × 3.0"' in body, "the 200 dpi size (4.5\" × 3.0\") is missing from the print-size table")
    expect("require CMYK" not in body, "the old 'most print methods require CMYK' warning is still shown")
    # ArtBot is drawn after the analysis, so it knows the file without an extra page refresh
    sidebar = page.locator('[data-testid="stSidebar"]').inner_text()
    expect("I can see your file" in sidebar and "photo_900x600.png" in sidebar,
           "ArtBot does not know about the image right after upload")
    app.no_errors()


def check_pure_ink_colors(app):
    page = app.fresh()
    app.upload_vector("pure_inks.pdf")
    app.generate()
    body = page.locator('[data-testid="stMain"]').inner_text()
    colors = body.split("Color Analysis", 1)[1]
    expect("K:100%" in colors, "pure black (K 100%) is painted in the file but not listed")
    expect("C:0% M:0% Y:100% K:0%" in colors, "pure yellow is painted in the file but not listed")
    expect("C:0% M:100% Y:100% K:0%" in colors, "red is not listed")
    expect("C:100% M:0% Y:0% K:0%" not in colors, "cyan is listed although it is never painted")
    expect("C:0% M:100% Y:0% K:0%" not in colors, "magenta is listed although it is never painted")
    pick(page, "Decoration method", "Screen Print")
    expect("3 colors detected = 3 screens" in decoration_text(page), "screen count should be 3 (black, yellow, red)")
    app.no_errors()


def check_color_count_wording(app):
    page = app.fresh()
    app.upload_vector("seven_colors.pdf")
    app.generate()
    body = page.locator('[data-testid="stMain"]').inner_text()
    expect("7 colors detected" in body, "the 7-color file did not trigger the color-count warning")
    expect("separate screen" in body, "the color-count warning does not explain cost per screen")
    expect("4-6 colors max" not in body, "the old '4-6 colors max' wording is still shown")
    pick(page, "Decoration method", "Screen Print")
    text = decoration_text(page)
    expect("7 colors detected = 7 screens" in text, "the Decoration Method Check does not agree on the color count")
    app.no_errors()


def check_raster_in_pdf(app):
    page = app.fresh()
    app.upload("raster_in.pdf")
    page.get_by_text("Raster image detected inside PDF").wait_for(timeout=30_000)
    page.get_by_text("Usable Print Sizes").wait_for(timeout=30_000)
    page.wait_for_timeout(2000)   # let the run finish: anything not redrawn is removed
    app.wait_for_sidebar()        # the sidebar must also be drawn on pages that stop early
    app.no_errors()


def check_large_pdf(app):
    page = app.fresh()
    app.upload_vector("letter_page.pdf")
    app.generate()
    m = metrics(page)
    expect(m.get("Dimensions (px)") == "3091 × 4000", f"letter page rendered at {m.get('Dimensions (px)')} (render cap is 4000 px)")
    expect(m.get("Size (inches)") == '8.5" x 11.0"', f"Size (inches) shows {m.get('Size (inches)')}")
    app.no_errors()


def check_white_logo_auto_background(app):
    app.fresh()
    app.upload_vector("white_logo.pdf")
    app.generate()
    img = Image.open(io.BytesIO(app.preview_png())).convert("RGB")
    corner = img.getpixel((2, 2))
    expect(max(corner) < 100, f"white logo on Auto got a light background {corner}; it should be dark")
    app.no_errors()


def pick(page, label, option):
    """Choose an option in a Streamlit dropdown by its label."""
    box = page.locator('[data-testid="stSelectbox"]').filter(has_text=label).first
    box.scroll_into_view_if_needed()
    box.locator('[data-baseweb="select"]').click()
    # Long lists only render the options in view, so type to filter first
    page.keyboard.type(option.split(" (")[0])
    page.get_by_role("option", name=option, exact=True).click()
    page.wait_for_timeout(1500)


def decoration_text(page):
    """Everything shown from the Decoration Method Check heading down."""
    body = page.locator('[data-testid="stMain"]').inner_text()
    expect("Decoration Method Check" in body, "Decoration Method Check section is missing")
    return body.split("Decoration Method Check", 1)[1]


def check_decoration_screen_print(app):
    page = app.fresh()
    app.upload_vector("logo_red_3x2in.pdf")
    app.generate()
    text = decoration_text(page)
    expect("Needs attention" not in text and "No problems found" not in text, "a verdict is shown before a method is picked")
    pick(page, "Decoration method", "Screen Print")
    text = decoration_text(page)
    expect("Needs attention for Screen Print" in text, "CMYK art without Pantone colors should need attention for screen print")
    expect("No Pantone" in text, "missing-Pantone warning is not shown")
    expect("Minimum order: 24 pieces" in text, "24-piece minimum is not shown")
    expect("Dubow Textile" in text, "Dubow Textile is not credited")
    expect("confirm with your specific decorator" in text, "the check-with-your-decorator advice is missing")
    app.no_errors()


def check_decoration_dtg_resolution(app):
    page = app.fresh()
    app.upload("photo_900x600.png")
    page.get_by_text("Usable Print Sizes").wait_for(timeout=30_000)
    page.wait_for_timeout(1500)
    pick(page, "Decoration method", "Digital Print (DTG)")
    pick(page, "Imprint location", 'Left / Right Chest (max 5" × 5")')
    text = decoration_text(page)
    expect("Not suitable as-is for Digital Print (DTG)" in text, "900 px image at 5\" wide should fail for DTG")
    expect("Only 180 dpi" in text, "the 180 dpi figure is not shown")
    expect("What to tell your customer" in text, "customer script is missing")
    width = page.get_by_label("Print width (in)")
    width.fill("3")
    width.press("Enter")
    page.wait_for_timeout(2000)
    text = decoration_text(page)
    expect("300 dpi" in text and "Only 180 dpi" not in text, "lowering the print width to 3\" should give 300 dpi")
    expect("No transparent background" in text, "image without transparency should be flagged for DTG")
    app.no_errors()


def check_decoration_embroidery_stitch_file(app):
    page = app.fresh()
    app.upload_vector("stitch.dst")
    app.generate()
    pick(page, "Decoration method", "Embroidery")
    pick(page, "Imprint location", 'Hat Front (max 5" × 2.25")')
    text = decoration_text(page)
    expect("No problems found for Embroidery" in text, "small stitch file should pass for a hat front")
    app.no_errors()


def check_decoration_dtfx_fades(app):
    page = app.fresh()
    app.upload("fade_1500px.png")
    page.get_by_text("Usable Print Sizes").wait_for(timeout=30_000)
    page.wait_for_timeout(1500)
    pick(page, "Decoration method", "DTFx (Direct to Film Transfer)")
    pick(page, "Imprint location", 'Left / Right Chest (max 5" × 5")')
    text = decoration_text(page)
    expect("Needs attention for DTFx" in text, "art that fades to transparent should need attention for DTFx")
    expect("fades or see-through areas" in text, "the fade warning is not shown")
    expect("300 dpi" in text, "1500 px at 5\" should report 300 dpi")
    app.no_errors()


def click_uploader_x(page):
    """Click the X next to the uploaded file's name."""
    page.locator('[data-testid="stFileUploaderDeleteBtn"] button').first.click()
    page.wait_for_timeout(2500)


def check_x_clears_raster(app):
    page = app.fresh()
    app.upload("photo_900x600.png")
    page.get_by_text("Usable Print Sizes").wait_for(timeout=30_000)
    page.wait_for_timeout(2000)
    click_uploader_x(page)
    body = page.locator("body").inner_text()
    expect("Usable Print Sizes" not in body, "raster results are still shown after clicking the X")
    expect("Decoration Method Check" not in body, "Decoration Method Check is still shown after clicking the X")
    expect("I can see your file" not in body, "ArtBot still says it can see the file after clicking the X")
    app.no_errors()


def check_x_clears_vector(app):
    page = app.fresh()
    app.upload_vector("logo_red_3x2in.pdf")
    app.generate()
    click_uploader_x(page)
    body = page.locator("body").inner_text()
    expect("Preview generated successfully" not in body, "the preview is still shown after clicking the X")
    expect("Color Analysis" not in body, "Color Analysis is still shown after clicking the X")
    expect("I can see your file" not in body, "ArtBot still says it can see the file after clicking the X")
    # and the app is ready for another file
    app.upload_vector("logo_blue_3x2in.pdf")
    app.generate()
    app.no_errors()


def check_results_survive_artbot(app):
    """Asking ArtBot reruns the page; the file's results must stay on screen."""
    page = app.fresh()
    app.upload("photo_900x600.png")
    page.get_by_text("Usable Print Sizes").wait_for(timeout=30_000)
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Difference between vector and raster?").click()
    page.get_by_role("button", name="🔄 Clear conversation").wait_for(timeout=90_000)
    page.wait_for_timeout(2000)
    body = page.locator("body").inner_text()
    expect("Usable Print Sizes" in body, "raster results disappeared after asking ArtBot a question")
    expect("I can see your file" in body, "ArtBot lost the file after a question")
    app.no_errors()


def download_pdf(page):
    """Click the PDF download button and return facts about the file that arrives."""
    import fitz
    with page.expect_download(timeout=30_000) as dl:
        page.get_by_role("button", name="Download PDF").click()
    path = dl.value.path()
    doc = fitz.open(path)
    first = doc[0]
    facts = {
        "name": dl.value.suggested_filename,
        "pages": doc.page_count,
        "paths": sum(len(p.get_drawings()) for p in doc),
        "images": sum(len(p.get_images()) for p in doc),
        "size_in": (round(first.rect.width / 72, 2), round(first.rect.height / 72, 2)),
        "objects": " ".join(doc.xref_object(x) for x in range(1, doc.xref_length())),
    }
    doc.close()
    return facts


def check_pdf_export_svg(app):
    page = app.fresh()
    app.upload_vector("logo_3x2in.svg")
    app.generate()
    expect(page.get_by_text("Vector preserved").count() > 0, "the app does not say the PDF is vector")
    pdf = download_pdf(page)
    expect(pdf["name"] == "logo_3x2in.pdf", f"download is named {pdf['name']}")
    expect(pdf["paths"] > 0 and pdf["images"] == 0, f"PDF from SVG has {pdf['paths']} vector paths and {pdf['images']} images")
    expect(pdf["size_in"] == (3.0, 2.0), f"PDF page is {pdf['size_in']} inches, the SVG is 3 x 2")
    app.no_errors()


def check_pdf_export_ai(app):
    page = app.fresh()
    app.upload_vector("logo_3x2in.ai")
    app.generate()
    expect(page.get_by_text("Vector preserved").count() > 0, "the app does not say the PDF is vector")
    pdf = download_pdf(page)
    expect(pdf["paths"] > 0 and pdf["images"] == 0, f"PDF from AI has {pdf['paths']} vector paths and {pdf['images']} images")
    expect(pdf["size_in"] == (3.0, 2.0), f"PDF page is {pdf['size_in']} inches, the AI file is 3 x 2")
    app.no_errors()


def check_pdf_export_multi_page_ai(app):
    page = app.fresh()
    app.upload_vector("two_artboards.ai")
    app.generate()
    pick(page, "Page", "Page 2 of 2")
    wait_for_metric(page, "Size (inches)", '5.0" x 4.0"')
    expect(page.get_by_text("The PDF contains all 2 pages").count() > 0, "no note that the PDF holds every page")
    pdf = download_pdf(page)
    expect(pdf["pages"] == 2, f"the PDF has {pdf['pages']} page(s); the AI file has 2 artboards")
    expect(pdf["paths"] > 0 and pdf["images"] == 0, "the multi-page PDF is not vector")
    app.no_errors()


def check_pdf_export_eps(app):
    page = app.fresh()
    app.upload_vector("logo_3x2in.eps")
    app.generate()
    expect(page.get_by_text("Vector preserved").count() > 0, "the app does not say the PDF is vector")
    pdf = download_pdf(page)
    expect(pdf["paths"] > 0 and pdf["images"] == 0, f"PDF from EPS has {pdf['paths']} vector paths and {pdf['images']} images")
    expect(pdf["size_in"] == (3.0, 2.0), f"PDF page is {pdf['size_in']} inches, the EPS artwork is 3 x 2")
    app.no_errors()


def check_pdf_export_eps_spot_color(app):
    page = app.fresh()
    app.upload_vector("spot_logo.eps")
    app.generate()
    pdf = download_pdf(page)
    expect(pdf["paths"] > 0 and pdf["images"] == 0, f"PDF has {pdf['paths']} vector paths and {pdf['images']} images")
    expect("/Separation" in pdf["objects"] and "PANTONE" in pdf["objects"],
           "the Pantone spot color did not survive the conversion to PDF")
    app.no_errors()


def check_pdf_export_flags_raster(app):
    page = app.fresh()
    app.upload_vector("picture_in.svg")
    app.generate()
    body = page.locator('[data-testid="stMain"]').inner_text()
    expect("Vector preserved" not in body, "a PDF containing a raster image is labelled as vector")
    expect("raster image" in body, "the app does not warn that the PDF contains a raster image")
    pdf = download_pdf(page)
    expect(pdf["images"] > 0, "expected the embedded picture to still be an image in the PDF")
    app.no_errors()


def check_pdf_export_not_offered_for_pdf(app):
    page = app.fresh()
    # First a file that DOES get a PDF download, then a PDF in the same session
    app.upload_vector("logo_3x2in.svg")
    app.generate()
    expect(page.get_by_role("button", name="Download PDF").count() == 1, "SVG should offer a PDF download")
    app.upload_vector("logo_red_3x2in.pdf")
    page.wait_for_timeout(1500)
    app.generate()
    expect(page.get_by_role("button", name="Download PDF").count() == 0, "a PDF upload should not offer a PDF conversion")
    expect(page.get_by_role("button", name="Download PNG").count() > 0, "Download PNG button is missing")
    app.no_errors()


def ask_artbot_example(page):
    """Click one of ArtBot's example questions and wait for the exchange to appear."""
    page.get_by_role("button", name="Difference between vector and raster?").click()
    page.get_by_role("button", name="🔄 Clear conversation").wait_for(timeout=90_000)
    page.wait_for_timeout(2500)


def chat_frame(page):
    """The frame that holds ArtBot's conversation."""
    for _ in range(40):
        for frame in page.frames:
            try:
                if frame.locator("#box .bot").count():
                    return frame
            except Exception:
                pass
        page.wait_for_timeout(500)
    raise AssertionError("ArtBot's answer did not appear in the conversation box")


def check_artbot_formatting(app):
    """Needs the app started with ARTBOT_FAKE_REPLY_FILE=tests/fake_artbot_reply.md."""
    page = app.fresh()
    question = "Is <b>this</b> ok & what about 5 < 6?"
    box = page.locator('[data-testid="stSidebar"]').get_by_placeholder("Ask anything...")
    box.fill(question)
    box.press("Enter")
    page.get_by_role("button", name="🔄 Clear conversation").wait_for(timeout=90_000)
    frame = chat_frame(page)
    answer = frame.locator(".bot").first
    text = answer.inner_text()
    expect(answer.locator("h1").count() == 1 and answer.locator("h1").inner_text().strip() == "Fonts Not Outlined",
           "the '# Fonts Not Outlined' heading is not rendered as a heading")
    expect("# Fonts" not in text and "**" not in text, "Markdown symbols are showing in ArtBot's answer")
    expect(answer.locator("strong").count() >= 3, "bold text is not rendered")
    expect(answer.locator("em").count() >= 1, "italic text is not rendered")
    expect(answer.locator("ul li").count() == 2 and answer.locator("ol li").count() == 2, "lists are not rendered")
    expect(answer.locator("blockquote").count() == 1, "the customer script is not rendered as a quote")
    expect(answer.locator("table td").count() >= 2, "the table is not rendered")
    expect(answer.locator("hr").count() == 1, "the divider is not rendered")
    # nothing typed by a user or written by the model may run or become markup
    expect(answer.locator("script").count() == 0 and answer.locator("b").count() == 0, "raw HTML from the answer was not escaped")
    expect(frame.evaluate("window.__artbotInjected") is None, "a script inside ArtBot's answer was executed")
    expect("<script>" in text and "<b>not bold</b>" in text, "stray markup should be shown as plain text")
    track = frame.evaluate("getComputedStyle(document.getElementById('box')).scrollbarColor")
    expect("13, 17, 23" in track, f"the chat box scrollbar track is not dark (scrollbar-color is {track!r})")
    asked = frame.locator(".user").first
    expect(asked.inner_text().strip() == question, f"the question is shown as {asked.inner_text()!r}")
    expect(asked.locator("b").count() == 0, "HTML typed by the user was not escaped")
    app.no_errors()


def check_x_clears_after_artbot(app):
    """The X must still clear everything after ArtBot has been used."""
    page = app.fresh()
    app.upload("photo_900x600.png")
    page.get_by_text("Usable Print Sizes").wait_for(timeout=30_000)
    page.wait_for_timeout(2000)
    ask_artbot_example(page)
    expect(page.get_by_text("Uploaded:").count() > 0, "the uploader forgot its file after an ArtBot question")
    click_uploader_x(page)
    body = page.locator("body").inner_text()
    expect("Usable Print Sizes" not in body, "raster results are still shown after ArtBot question + X")
    expect("I can see your file" not in body, "ArtBot still says it can see the file after the X")

    page = app.fresh()
    app.upload_vector("logo_red_3x2in.pdf")
    app.generate()
    ask_artbot_example(page)
    click_uploader_x(page)
    body = page.locator("body").inner_text()
    expect("Preview generated successfully" not in body, "the preview is still shown after ArtBot question + X")
    expect("I can see your file" not in body, "ArtBot still says it can see the file after the X")
    app.no_errors()


def check_method_choice_survives_artbot(app):
    page = app.fresh()
    app.upload_vector("logo_red_3x2in.pdf")
    app.generate()
    pick(page, "Decoration method", "Screen Print")
    expect("Needs attention for Screen Print" in decoration_text(page), "screen print verdict not shown")
    ask_artbot_example(page)
    expect("Needs attention for Screen Print" in decoration_text(page),
           "the Decoration Method Check reset itself after an ArtBot question")
    app.no_errors()


def check_indesign_thumbnail(app):
    page = app.fresh()
    app.upload("layout.indd")
    page.get_by_text("InDesign file: thumbnail only").wait_for(timeout=30_000)
    main = page.locator('[data-testid="stMain"]')
    body = main.inner_text()
    expect(main.locator('[data-testid="stImage"] img').count() == 1, "the InDesign thumbnail is not shown")
    expect("256 × 198 px" in body and "Adobe InDesign 18.4" in body and "2025-05-09" in body,
           "thumbnail size, app or save date missing (should come from the newest InDesign save)")
    expect("not usable for production" in body, "the thumbnail is not labelled as unusable for production")
    expect("Export" in body and "PDF" in body, "export instructions for InDesign files are missing")
    expect("Generate Preview" not in body, "an InDesign file must not reach the normal preview flow")
    page.wait_for_timeout(2000)   # let the run finish: anything not redrawn is removed
    app.wait_for_sidebar()        # the sidebar must also be drawn on pages that stop early
    app.no_errors()


def check_indesign_without_preview(app):
    page = app.fresh()
    app.upload("no_preview.indd")
    page.get_by_text("InDesign Files Not Supported").wait_for(timeout=30_000)
    body = page.locator('[data-testid="stMain"]').inner_text()
    expect("Export" in body and "PDF" in body, "export instructions for InDesign files are missing")
    page.wait_for_timeout(2000)
    app.wait_for_sidebar()
    app.no_errors()


def check_gimp_preview(app):
    from PIL import Image
    page = app.fresh()
    app.upload("artwork.xcf")
    page.get_by_text("Usable Print Sizes").wait_for(timeout=60_000)
    main = page.locator('[data-testid="stMain"]')
    body = main.inner_text()
    expect("3 layers flattened into one image" in body and "1 hidden layer left out" in body,
           "the layer summary for the GIMP file is missing or wrong")
    expect(metrics(page).get("Dimensions") == "300 × 200 px", f"Dimensions show {metrics(page).get('Dimensions')}")
    expect('1.0" × 0.67"' in body, "the 300 dpi print size (1.0\" × 0.67\") is missing: resolution not read from the GIMP file")
    expect("Decoration Method Check" in body, "the Decoration Method Check is missing for a GIMP file")
    expect("could not be opened" not in body and "Files Not Supported" not in body, "a readable GIMP file was refused")
    with page.expect_download(timeout=30_000) as dl:
        page.get_by_role("button", name="Download PNG").click()
    expect(dl.value.suggested_filename == "artwork.png", f"download is named {dl.value.suggested_filename}")
    img = Image.open(dl.value.path())
    expect(img.size == (300, 200) and img.mode == "RGBA", f"downloaded PNG is {img.size} {img.mode}")
    # red box from the middle layer, cream background, and the hidden green layer absent
    red, cream = img.getpixel((60, 60)), img.getpixel((5, 195))
    expect(red[0] > 180 and red[1] < 60, f"the red layer is missing from the flattened image: {red}")
    expect(cream[:3] == (245, 240, 225), f"background is {cream}; the hidden green layer may have been drawn")
    sidebar = page.locator('[data-testid="stSidebar"]').inner_text()
    expect("I can see your file" in sidebar and "artwork.xcf" in sidebar, "ArtBot does not know about the GIMP file")
    # the X clears it like any other file
    click_uploader_x(page)
    page.get_by_text("Usable Print Sizes").wait_for(state="detached", timeout=20_000)
    app.no_errors()


def check_gimp_damaged(app):
    page = app.fresh()
    app.upload("damaged.xcf")
    page.get_by_text("This GIMP file could not be opened").wait_for(timeout=30_000)
    body = page.locator('[data-testid="stMain"]').inner_text()
    expect("Export As" in body and "PNG" in body, "export instructions for GIMP files are missing")
    expect("Could not convert" not in body, "the old 'Could not convert file' error is shown for a GIMP file")
    page.wait_for_timeout(2000)   # let the run finish: anything not redrawn is removed
    app.wait_for_sidebar()        # the sidebar must also be drawn on pages that stop early
    app.no_errors()


CHECKS = [
    ("App loads with uploader and ArtBot sidebar, one list of file types", check_home),
    ("Vector PDF: preview, real size in inches, CMYK color analysis", check_vector_pdf),
    ("Mockup Builder gets the current file after switching files", check_mockup_after_switch),
    ("SVG without units: preview, size shown as Scalable", check_svg),
    ("SVG with real-world units: size in inches", check_svg_with_units),
    ("Multi-page PDF: page picker switches preview, size, colors and method check", check_multi_page_pdf),
    ("Multi-page PDF: a scanned first page does not block the vector page", check_page_picker_reaches_vector_page),
    ("Background buttons switch the preview instantly, without Generate Preview", check_instant_background),
    ("EPS preview, size and colors including pure black (Ghostscript)", check_eps),
    ("EPS color mode comes from the file's ink list, not the word 'Separation' (Ghostscript)", check_eps_color_mode_from_header),
    ("Font Check flags live text in a PDF, with embedded / not embedded", check_fonts_pdf),
    ("Font Check flags live text in an SVG", check_fonts_svg),
    ("Font Check flags live text in an EPS (Ghostscript)", check_fonts_eps),
    ("Decoration check: screen print warnings, minimum, Dubow credit, decorator advice", check_decoration_screen_print),
    ("Decoration check: DTG resolution at the chosen location and print width", check_decoration_dtg_resolution),
    ("Decoration check: stitch file passes for a hat front", check_decoration_embroidery_stitch_file),
    ("Decoration check: DTFx flags art that fades to transparent", check_decoration_dtfx_fades),
    ("PDF export from SVG is vector and the right size", check_pdf_export_svg),
    ("PDF export from AI is vector and the right size", check_pdf_export_ai),
    ("PDF export from a multi-artboard AI keeps every page", check_pdf_export_multi_page_ai),
    ("PDF export from EPS is vector and the right size (Ghostscript)", check_pdf_export_eps),
    ("PDF export from EPS keeps the Pantone spot color (Ghostscript)", check_pdf_export_eps_spot_color),
    ("PDF export warns when the original contains a raster image", check_pdf_export_flags_raster),
    ("PDF export is not offered for files that are already PDF", check_pdf_export_not_offered_for_pdf),
    ("Embroidery file: stitch count and real size", check_embroidery),
    ("Raster image: quality verdict, print sizes at 300 and 200 dpi only", check_raster_png),
    ("Pure black and pure yellow are listed when painted; unused colors are not", check_pure_ink_colors),
    ("Color-count warning matches the Decoration Method Check (no fixed maximum)", check_color_count_wording),
    ("Raster-in-PDF is detected", check_raster_in_pdf),
    ("Letter-size PDF renders within the 4000 px cap", check_large_pdf),
    ("White logo gets a dark Auto background", check_white_logo_auto_background),
    ("The X on the uploader clears a raster file's results", check_x_clears_raster),
    ("The X on the uploader clears a vector file's results", check_x_clears_vector),
    ("Results stay on screen after asking ArtBot a question", check_results_survive_artbot),
    ("ArtBot answers show formatted (headings, bold, lists, quotes) and stray markup is escaped", check_artbot_formatting),
    ("The X still clears everything after an ArtBot question", check_x_clears_after_artbot),
    ("Decoration Method Check keeps its selection after an ArtBot question", check_method_choice_survives_artbot),
    ("InDesign upload shows the thumbnail saved in the file, plus export instructions", check_indesign_thumbnail),
    ("InDesign upload without a saved preview shows export instructions", check_indesign_without_preview),
    ("GIMP (.xcf) upload is flattened, analyzed and downloadable as PNG", check_gimp_preview),
    ("Damaged GIMP file shows export instructions", check_gimp_damaged),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8501")
    parser.add_argument("--fixtures", default="tests/fixtures")
    parser.add_argument("--screenshots", default="test-screenshots")
    args = parser.parse_args()
    os.makedirs(args.screenshots, exist_ok=True)
    skip_eps = os.environ.get("SKIP_EPS") == "1"

    with sync_playwright() as pw:
        launch = {"args": ["--no-sandbox"]}
        if os.environ.get("PLAYWRIGHT_CHANNEL"):
            launch["channel"] = os.environ["PLAYWRIGHT_CHANNEL"]
        browser = pw.chromium.launch(**launch)
        context = browser.new_context(viewport={"width": 1500, "height": 1100})
        # Never let a test run show up in the real Google Analytics property
        context.route(re.compile(r"googletagmanager\.com|google-analytics\.com"), lambda route: route.abort())
        app = App(context, args.url, args.fixtures, args.screenshots)

        for number, (name, check) in enumerate(CHECKS, 1):
            if check in (check_eps, check_fonts_eps, check_pdf_export_eps, check_pdf_export_eps_spot_color,
                         check_eps_color_mode_from_header) and skip_eps:
                RESULTS.append((name, None, "skipped (SKIP_EPS=1)"))
                continue
            try:
                check(app)
                RESULTS.append((name, True, ""))
            except Exception as err:  # keep going so one failure doesn't hide the rest
                detail = str(err).strip().splitlines()[0] if str(err).strip() else type(err).__name__
                RESULTS.append((name, False, detail))
                traceback.print_exc()
                try:
                    app.page.screenshot(path=os.path.join(args.screenshots, f"failed-{number:02d}.png"), full_page=True)
                except Exception:
                    pass
        browser.close()

    icon = {True: "✅", False: "❌", None: "⏭️"}
    lines = [f"{icon[ok]} {name}" + (f" — {detail}" if detail else "") for name, ok, detail in RESULTS]
    failed = sum(1 for _, ok, _ in RESULTS if ok is False)
    passed = sum(1 for _, ok, _ in RESULTS if ok is True)
    headline = f"ArtCheck browser test: {passed} passed, {failed} failed"
    print("\n" + headline + "\n" + "\n".join(lines))

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(f"## {headline}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

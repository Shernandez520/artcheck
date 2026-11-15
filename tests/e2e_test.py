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
        return self.page

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
    expect(page.get_by_text("Ask ArtBot").first.is_visible(), "ArtBot sidebar is missing")
    expect(page.locator("input[type=file]").count() == 1, "file uploader is missing")
    app.no_errors()


def check_vector_pdf(app):
    page = app.fresh()
    app.upload_vector("logo_red_3x2in.pdf")
    app.generate()
    m = metrics(page)
    expect(m.get("Size (inches)") == '3.0" x 2.0"', f"expected 3.0\" x 2.0\", page shows {m.get('Size (inches)')}")
    expect("Vector" in m.get("File Type", ""), f"File Type shows {m.get('File Type')}")
    expect(page.get_by_text("Color Analysis").count() > 0, "Color Analysis section is missing")
    expect(page.get_by_text("Document Color Mode: CMYK").count() > 0, "CMYK document was not reported as CMYK")
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
    expect(metrics(page).get("Dimensions (px)") == "1200 × 800", f"dimensions show {metrics(page).get('Dimensions (px)')}")
    app.no_errors()


def check_eps(app):
    page = app.fresh()
    app.upload_vector("logo_3x2in.eps")
    app.generate()
    m = metrics(page)
    expect(m.get("Size (inches)") == '3.0" x 2.0"', f"expected 3.0\" x 2.0\", page shows {m.get('Size (inches)')}")
    expect(page.get_by_text("Color Analysis").count() > 0, "Color Analysis section is missing")
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
    app.no_errors()


def check_raster_in_pdf(app):
    page = app.fresh()
    app.upload("raster_in.pdf")
    page.get_by_text("Raster image detected inside PDF").wait_for(timeout=30_000)
    page.get_by_text("Usable Print Sizes").wait_for(timeout=30_000)
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


def check_indesign_message(app):
    page = app.fresh()
    app.upload("layout.indd")
    page.get_by_text("InDesign Files Not Supported").wait_for(timeout=30_000)
    app.no_errors()


CHECKS = [
    ("App loads with uploader and ArtBot sidebar", check_home),
    ("Vector PDF: preview, real size in inches, CMYK color analysis", check_vector_pdf),
    ("Mockup Builder gets the current file after switching files", check_mockup_after_switch),
    ("SVG preview", check_svg),
    ("EPS preview and size (Ghostscript)", check_eps),
    ("Embroidery file: stitch count and real size", check_embroidery),
    ("Raster image: quality verdict", check_raster_png),
    ("Raster-in-PDF is detected", check_raster_in_pdf),
    ("Letter-size PDF renders within the 4000 px cap", check_large_pdf),
    ("White logo gets a dark Auto background", check_white_logo_auto_background),
    ("InDesign upload shows export instructions", check_indesign_message),
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
            if check is check_eps and skip_eps:
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

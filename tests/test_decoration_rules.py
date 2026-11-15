"""Unit tests for decoration_rules.py (no browser, no Streamlit).

    python tests/test_decoration_rules.py

Exits 0 when every case passes and 1 otherwise.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import decoration_rules as dr  # noqa: E402

RESULTS = []


def case(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except Exception as err:
            RESULTS.append((name, False, f"{type(err).__name__}: {err}"))
        return fn
    return wrap


def vector(colors=3, spots=0, gradients=False, mode="CMYK", size=(3.0, 2.0), live_text=False, pages=1, hairline=False, opacity=100):
    result = {"file_type": "Vector (PDF)", "width": 2160, "height": 1440, "page_count": pages,
              "font_check": {"live_text": live_text}}
    if size:
        result["width_in"], result["height_in"] = size
    color_data = {
        "fills": [{"label": f"c{i}", "opacity": opacity} for i in range(colors - spots)],
        "spot_colors": [{"label": f"PANTONE {i}"} for i in range(spots)],
        "strokes": [{"width": 0.25}] if hairline else [],
        "gradients": [{"type": "gradient"}] if gradients else [],
        "color_mode": mode,
    }
    return dr.facts_from_vector(result, color_data)


def raster(w, h, verdict="marginal", alpha=False, soft=False, mode="RGB"):
    return dr.facts_from_raster({"width_px": w, "height_px": h, "verdict": verdict, "color_mode": mode,
                                 "has_transparency": alpha, "soft_transparency": soft}, "art.png")


def stitch(w_mm, h_mm):
    return dr.facts_from_vector({"file_type": "embroidery", "width": 1200, "height": 800,
                                 "width_in": round(w_mm / 25.4, 2), "height_in": round(h_mm / 25.4, 2),
                                 "embroidery_info": {"stitch_count": 5200, "unique_color_count": 3}}, None)


def text(ev):
    return " ".join(ev["fails"] + ev["warns"] + ev["notes"] + ev["confirm"])


@case("print area is the smaller of the method and location maximums")
def _():
    assert dr.print_area("screen_print", "full_front") == (14.5, 15.0)
    assert dr.print_area("embroidery", "full_back") == (10.0, 10.0)
    assert dr.print_area("embroidery", "hat_front") == (5.0, 2.25)
    assert dr.print_area("dtg") == (15.0, 19.0)
    assert dr.print_area("hard_goods") is None


@case("locations are offered for apparel methods only")
def _():
    assert "left_chest" in dr.location_keys("dtg")
    assert dr.location_keys("stickers") == [] and dr.location_keys("hard_goods") == []


@case("screen print: spot-color vector passes, with the 24-piece minimum noted")
def _():
    ev = dr.evaluate(vector(colors=2, spots=2, mode="Spot Color"), "screen_print", "left_chest")
    assert ev["verdict"] == "pass", ev
    assert "Minimum order: 24 pieces" in text(ev) and "2 colors detected = 2 screens" in text(ev)


@case("screen print: no Pantone colors is a warning, gradients become halftones")
def _():
    ev = dr.evaluate(vector(colors=3, spots=0, gradients=True), "screen_print")
    assert ev["verdict"] == "warn" and not ev["fails"], ev
    assert "No Pantone" in text(ev) and "halftones" in text(ev)


@case("screen print: there is no maximum color count (information only)")
def _():
    ev = dr.evaluate(vector(colors=12, spots=12, mode="Spot Color"), "screen_print")
    assert ev["verdict"] == "pass" and "12 colors detected = 12 screens" in text(ev), ev


@case("embroidery: gradients fail, and 3/16 inch text is on the confirm list")
def _():
    ev = dr.evaluate(vector(gradients=True), "embroidery", "left_chest")
    assert ev["verdict"] == "fail" and "Gradients" in ev["fails"][0], ev
    assert any('3/16"' in c for c in ev["confirm"])


@case("embroidery: a supplied stitch file that fits passes")
def _():
    ev = dr.evaluate(stitch(90, 60), "embroidery", "left_chest")
    assert ev["verdict"] == "pass" and "accepted" in text(ev), ev


@case("embroidery: a stitch file bigger than the hat front fails")
def _():
    ev = dr.evaluate(stitch(100, 80), "embroidery", "hat_front")
    assert ev["verdict"] == "fail" and "re-digitized" in ev["fails"][0], ev


@case("a stitch file can't be used for a print method")
def _():
    assert dr.evaluate(stitch(90, 60), "dtg")["verdict"] == "fail"


@case("DTG: 900 px image at a 5 inch left chest is 180 dpi and fails")
def _():
    f = raster(900, 600, alpha=True)
    assert dr.max_print_width(f, "dtg", "left_chest") == 5.0
    ev = dr.evaluate(f, "dtg", "left_chest")
    assert ev["dpi"] == 180 and ev["verdict"] == "fail" and "180 dpi" in ev["fails"][0], ev
    assert "1,000 px" in ev["asks"][0]


@case("DTG: the same image at 3 inches wide is 300 dpi and passes")
def _():
    ev = dr.evaluate(raster(900, 600, alpha=True), "dtg", "left_chest", print_width=3)
    assert ev["dpi"] == 300 and ev["verdict"] == "pass", ev


@case("DTG: 200-299 dpi is a warning")
def _():
    ev = dr.evaluate(raster(3000, 3000, verdict="good", alpha=True), "dtg", "full_front")
    assert ev["print_size"] == (15.0, 15.0) and ev["dpi"] == 200 and ev["verdict"] == "warn", ev


@case("DTG: an image with no transparent background gets a warning")
def _():
    ev = dr.evaluate(raster(3000, 2000, verdict="good", alpha=False), "dtg", "left_chest")
    assert ev["verdict"] == "warn" and "No transparent background" in text(ev), ev


@case("print width can't exceed what the area allows")
def _():
    ev = dr.evaluate(raster(3000, 3000, verdict="good", alpha=True), "dtg", "left_chest", print_width=40)
    assert ev["print_size"] == (5.0, 5.0), ev


@case("raster with no location reports printable sizes and uses the general rating")
def _():
    ev = dr.evaluate(raster(900, 600, verdict="poor", alpha=True), "dtg")
    assert ev["verdict"] == "fail" and ev["dpi"] is None and '3" × 2" at 300 dpi' in text(ev), ev


@case("DTFx: fades are a warning, and the 1 mm detail rule is on the confirm list")
def _():
    ev = dr.evaluate(raster(4000, 4000, verdict="good", alpha=True, soft=True), "dtfx", "left_chest")
    assert ev["verdict"] == "warn" and "fades" in text(ev) and "1 mm" in text(ev), ev


@case("laser etch: multi-color art is a warning")
def _():
    ev = dr.evaluate(vector(colors=3, spots=3, mode="Spot Color"), "laser_etch")
    assert ev["verdict"] == "warn" and "tone-on-tone" in text(ev), ev


@case("live text is a warning for every method")
def _():
    for key in dr.method_keys():
        ev = dr.evaluate(vector(colors=1, spots=1, mode="Spot Color", live_text=True), key)
        assert any("not outlined" in w for w in ev["warns"]), key


@case("hard goods: template and inventory notes, no size check")
def _():
    f = vector(colors=1, spots=1, mode="Spot Color")
    ev = dr.evaluate(f, "hard_goods")
    assert ev["verdict"] == "pass" and "template" in text(ev) and not dr.asks_for_print_width(f, "hard_goods")


@case("stickers and buttons take a print width without a location")
def _():
    f = raster(900, 900, alpha=True)
    assert dr.asks_for_print_width(f, "buttons") and dr.max_print_width(f, "buttons") == 3.0
    assert dr.evaluate(f, "buttons")["dpi"] == 300


@case("multi-page files are noted")
def _():
    assert "page 1 of 3" in text(dr.evaluate(vector(spots=3, mode="Spot Color", pages=3), "dtg"))


@case("customer script and ArtBot summary are produced")
def _():
    ev = dr.evaluate(raster(900, 600, alpha=False), "dtg", "left_chest")
    assert "could you send us" in dr.customer_script(ev)
    assert "NOT SUITABLE AS-IS" in dr.artbot_summary(ev) and "Left / Right Chest" in dr.artbot_summary(ev)
    assert dr.customer_script(dr.evaluate(stitch(90, 60), "embroidery")) is None


@case("every method evaluates every kind of file without crashing")
def _():
    files = [vector(), vector(size=None), raster(10, 10, verdict="poor"), raster(5000, 100, verdict="good", alpha=True),
             stitch(50, 50), dr.facts_from_vector({"file_type": "SVG (embedded raster)", "width": 1200, "height": 800}, None),
             dr.facts_from_vector({}, None), dr.facts_from_raster({}, "")]
    for f in files:
        for m in dr.method_keys():
            for loc in [None] + dr.location_keys(m):
                dr.artbot_summary(dr.evaluate(f, m, loc))
                dr.asks_for_print_width(f, m, loc)


if __name__ == "__main__":
    failed = [r for r in RESULTS if not r[1]]
    headline = f"Decoration rules: {len(RESULTS) - len(failed)} passed, {len(failed)} failed"
    lines = [("✅ " if ok else "❌ ") + name + (f" — {detail}" if detail else "") for name, ok, detail in RESULTS]
    print(headline + "\n" + "\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## {headline}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
    sys.exit(1 if failed else 0)

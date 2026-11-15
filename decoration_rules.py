"""
Decoration method pre-screen rules for ArtCheck.

Pure Python on purpose (no Streamlit import) so the rules can be unit-tested
on their own: see tests/test_decoration_rules.py.

WHERE THE NUMBERS COME FROM
Maximum imprint sizes, minimum quantities, minimum text/detail sizes and the
DTG resolution rule come from Dubow Textile's published info sheets and the
imprint-location chart on dubowtextile.com (read November 2026). They are used
as general guidance: every decorator is different, and the UI says so.
Rules marked "general" below are common industry practice, not Dubow numbers.
Dubow publishes no maximum screen-print color count and no stitch-count or
thread-color limit, so those are reported as information only.
"""
import math

GUIDE_NAME = "Dubow Textile"
GUIDE_URL = "https://dubowtextile.com/Info-Sheets"
DISCLAIMER = (
    "This is a general guide based on Dubow Textile's published guidelines. Every decorator has "
    "its own requirements — always confirm with your specific decorator before quoting or ordering."
)

# General resolution guideline. Dubow states it for Digital Print (DTG):
# "at least 200dpi (300dpi is recommended)" at the size requested.
MIN_DPI = 200
GOOD_DPI = 300

# key -> label, max imprint (W, H) in inches, minimum quantity, behaviour flags
METHODS = {
    "screen_print": {"label": "Screen Print", "max": (14.5, 18.0), "min_qty": 24, "apparel": True, "dpi_rule": True},
    "embroidery": {"label": "Embroidery", "max": (10.0, 10.0), "min_qty": 1, "apparel": True, "dpi_rule": False},
    "dtfx": {"label": "DTFx (Direct to Film Transfer)", "max": (14.0, 18.0), "min_qty": 1, "apparel": True, "dpi_rule": True},
    "dtg": {"label": "Digital Print (DTG)", "max": (15.0, 19.0), "min_qty": 1, "apparel": True, "dpi_rule": True},
    "dye_sub": {"label": "Dye Sublimation", "max": (15.0, 19.0), "min_qty": 1, "apparel": True, "dpi_rule": True},
    "laser_etch": {"label": "Laser Etch", "max": (22.0, 11.0), "min_qty": 1, "apparel": True, "dpi_rule": False},
    "stickers": {"label": "Stickers", "max": (9.8, 14.0), "min_qty": 1, "apparel": False, "dpi_rule": True},
    "buttons": {"label": "Buttons / Magnets", "max": (3.0, 3.0), "min_qty": 1, "apparel": False, "dpi_rule": True},
    "hard_goods": {"label": "Hard Goods (flatbed, cylindrical, drinkware)", "max": None, "min_qty": 1,
                   "apparel": False, "dpi_rule": False},
}

# Dubow imprint-location chart: typical maximums in inches (W, H), Adult L
LOCATIONS = {
    "left_chest": ("Left / Right Chest", (5.0, 5.0)),
    "full_front": ("Full Front", (15.0, 15.0)),
    "full_back": ("Full Back", (15.0, 15.0)),
    "back_locker": ("Back Locker / Yoke", (5.0, 5.0)),
    "sleeve": ("Sleeve", (5.0, 5.0)),
    "sleeve_vertical": ("Sleeve — Vertical", (4.0, 16.0)),
    "cuff": ("On Cuff", (4.0, 2.5)),
    "pocket": ("On / Opposite Pocket", (5.0, 5.0)),
    "thigh_hip": ("Thigh / Hip", (5.0, 5.0)),
    "leg_vertical": ("Down Leg", (4.0, 16.0)),
    "hat_front": ("Hat Front", (5.0, 2.25)),
    "hat_back": ("Hat Back", (4.0, 2.0)),
    "hat_side": ("Hat Side", (3.75, 2.0)),
    "bag_front": ("Bag Front / Back", (12.0, 12.0)),
    "bag_pocket": ("Bag Bottom Pocket", (6.0, 6.0)),
    "neck_label": ("Neck Label", (2.5, 2.5)),
    "blanket": ("Blanket / Towel", (15.0, 15.0)),
}


def _n(value):
    """Inches without trailing zeros: 5.0 -> '5', 14.5 -> '14.5'."""
    return f"{round(float(value), 2):g}"


def _size(w, h):
    return f'{_n(w)}" × {_n(h)}"'


def method_keys():
    return list(METHODS.keys())


def method_label(key):
    return METHODS[key]["label"]


def location_keys(method_key):
    """Imprint locations that apply to a method (apparel methods only)."""
    if method_key in METHODS and METHODS[method_key]["apparel"]:
        return list(LOCATIONS.keys())
    return []


def location_label(key):
    name, (w, h) = LOCATIONS[key]
    return f"{name} (max {_size(w, h)})"


def print_area(method_key, location_key=None):
    """Largest imprint (W, H) for the method, narrowed by the location when one is chosen."""
    method_max = METHODS[method_key]["max"]
    if location_key and location_key in LOCATIONS and METHODS[method_key]["apparel"]:
        loc = LOCATIONS[location_key][1]
        if method_max:
            return (min(loc[0], method_max[0]), min(loc[1], method_max[1]))
        return loc
    return method_max


def max_print_width(facts, method_key, location_key=None):
    """Widest the art can print in the area while keeping its proportions."""
    area = print_area(method_key, location_key)
    aspect = facts.get("aspect")
    if not area or not aspect:
        return None
    return round(min(area[0], area[1] * aspect), 2)


def asks_for_print_width(facts, method_key, location_key=None):
    """True when a print-width box should be shown for this combination."""
    if method_key not in METHODS or facts.get("kind") == "embroidery":
        return False
    if METHODS[method_key]["max"] is None:
        return False
    if METHODS[method_key]["apparel"] and not location_key:
        return False
    return max_print_width(facts, method_key, location_key) is not None


# ---------------------------------------------------------------- facts

def facts_from_vector(result, color_data):
    """Facts about a file that went through the vector / embroidery preview flow."""
    result = result or {}
    file_type = (result.get("file_type") or "").lower()
    if file_type == "embroidery":
        kind = "embroidery"
    elif "embedded raster" in file_type:
        kind = "raster_in_vector"
    else:
        kind = "vector"

    facts = {
        "kind": kind,
        "aspect": None,
        "size_in": None,
        "px": None,
        "raster_verdict": None,
        "has_alpha": None,
        "soft_alpha": False,
        "color_count": None,
        "spot_count": None,
        "has_gradients": False,
        "hairlines": False,
        "color_mode": None,
        "live_text": bool((result.get("font_check") or {}).get("live_text")),
        "page_count": result.get("page_count") or 1,
        "stitch_count": None,
        "thread_colors": None,
    }
    if result.get("width") and result.get("height"):
        facts["aspect"] = result["width"] / result["height"]
    if result.get("width_in") and result.get("height_in"):
        facts["size_in"] = (float(result["width_in"]), float(result["height_in"]))
        facts["aspect"] = facts["size_in"][0] / facts["size_in"][1]

    emb = result.get("embroidery_info")
    if kind == "embroidery" and isinstance(emb, dict):
        facts["stitch_count"] = emb.get("stitch_count")
        facts["thread_colors"] = emb.get("unique_color_count")

    if color_data:
        fills = color_data.get("fills") or []
        spots = color_data.get("spot_colors") or []
        strokes = color_data.get("strokes") or []
        facts["color_count"] = len(fills) + len(spots)
        facts["spot_count"] = len(spots)
        facts["has_gradients"] = bool(color_data.get("gradients"))
        facts["hairlines"] = any((s.get("width", 1) or 0) < 0.5 for s in strokes)
        facts["color_mode"] = color_data.get("color_mode")
        facts["soft_alpha"] = any((f.get("opacity", 100) or 100) < 100 for f in fills)
    return facts


def facts_from_raster(analysis, filename=""):
    """Facts about a raster upload (or the image pulled out of a raster-only PDF)."""
    analysis = analysis or {}
    w, h = analysis.get("width_px") or 0, analysis.get("height_px") or 0
    return {
        "kind": "raster",
        "aspect": (w / h) if w and h else None,
        "size_in": None,
        "px": (w, h) if w and h else None,
        "raster_verdict": analysis.get("verdict"),
        "has_alpha": analysis.get("has_transparency"),
        "soft_alpha": bool(analysis.get("soft_transparency")),
        "color_count": None,
        "spot_count": None,
        "has_gradients": False,
        "hairlines": False,
        "color_mode": analysis.get("color_mode"),
        "live_text": False,
        "page_count": 1,
        "stitch_count": None,
        "thread_colors": None,
    }


# ---------------------------------------------------------------- evaluation

def evaluate(facts, method_key, location_key=None, print_width=None):
    """Screen the file for one decoration method.

    Returns {'verdict': 'pass' | 'warn' | 'fail', 'fails': [...], 'warns': [...],
             'notes': [...], 'confirm': [...], 'asks': [...], 'area', 'print_size', 'dpi',
             'method', 'location'}
    """
    method = METHODS[method_key]
    label = method["label"]
    kind = facts.get("kind")
    is_raster = kind == "raster"
    rasterish = kind in ("raster", "raster_in_vector")
    fails, warns, notes, confirm, asks = [], [], [], [], []

    area = print_area(method_key, location_key)
    max_w = max_print_width(facts, method_key, location_key)
    aspect = facts.get("aspect")
    print_size, dpi = None, None

    # ---- size
    if kind == "embroidery":
        if method_key != "embroidery":
            fails.append(f"This is an embroidery stitch file. It can only be used for embroidery, not {label}.")
            asks.append("the original artwork as a vector file (.ai, .eps or .pdf)")
        elif facts.get("size_in") and area:
            w, h = facts["size_in"]
            if w > area[0] + 0.01 or h > area[1] + 0.01:
                fails.append(
                    f"The stitch file is {_size(w, h)}, larger than the {_size(*area)} maximum here. "
                    "Stitch files can't simply be scaled down — the design has to be re-digitized smaller."
                )
                asks.append(f"a version of the design digitized to fit within {_size(*area)}")
            else:
                notes.append(f"Stitch file size {_size(w, h)} fits within the {_size(*area)} maximum.")
    elif max_w and aspect and asks_for_print_width(facts, method_key, location_key):
        width = max_w if not print_width else max(0.1, min(float(print_width), max_w))
        print_size = (round(width, 2), round(width / aspect, 2))
        notes.append(f"Checked at a print size of {_size(*print_size)} (the most this area allows is {_size(max_w, max_w / aspect)}).")
        if kind == "vector" and facts.get("size_in") and facts["size_in"][0] > max_w + 0.01:
            notes.append(f"The file is built at {_size(*facts['size_in'])}; vector art scales down to fit without losing quality.")
    elif area and method["apparel"] and not location_key:
        notes.append(f"Largest imprint for {label}: {_size(*area)}. Pick an imprint location to check a specific size.")

    # ---- resolution (raster only)
    if is_raster and facts.get("px"):
        px_w, px_h = facts["px"]
        if method["dpi_rule"] and print_size:
            dpi = int(px_w / print_size[0])
            clean_w = px_w / MIN_DPI
            if dpi < MIN_DPI:
                fails.append(
                    f"Only {dpi} dpi at {_size(*print_size)}. The minimum is {MIN_DPI} dpi at print size "
                    f"({GOOD_DPI} recommended). This image prints cleanly up to about {_n(clean_w)}\" wide."
                )
                asks.append(
                    f"a larger image — at least {math.ceil(print_size[0] * MIN_DPI):,} px wide for a "
                    f"{_n(print_size[0])}\" print ({math.ceil(print_size[0] * GOOD_DPI):,} px recommended) — or the original vector file"
                )
            elif dpi < GOOD_DPI:
                warns.append(
                    f"{dpi} dpi at {_size(*print_size)} — above the {MIN_DPI} dpi minimum but below the recommended {GOOD_DPI}."
                )
            else:
                notes.append(f"{dpi} dpi at {_size(*print_size)} — meets the recommended {GOOD_DPI} dpi.")
        elif method["dpi_rule"]:
            notes.append(
                f"This image can print up to {_size(px_w / GOOD_DPI, px_h / GOOD_DPI)} at {GOOD_DPI} dpi (recommended) "
                f"or {_size(px_w / MIN_DPI, px_h / MIN_DPI)} at {MIN_DPI} dpi (minimum)."
            )
            if facts.get("raster_verdict") == "poor":
                fails.append("The image is too small / low resolution to print clearly.")
                asks.append("a higher-resolution image or the original vector file")
            elif facts.get("raster_verdict") == "marginal":
                warns.append("Borderline resolution — fine for small imprints only.")
        elif facts.get("raster_verdict") == "poor":
            warns.append("Low-resolution image — it may not be clear enough to work from.")
            asks.append("a higher-resolution image or the original vector file")

    if kind == "raster_in_vector":
        warns.append("This file is a raster image saved inside a vector file, so its resolution could not be checked here.")
        asks.append("the original image file, or true vector artwork")

    # ---- method-specific rules
    colors = facts.get("color_count")

    if method_key == "screen_print":
        if rasterish:
            warns.append("Vector art is preferred for screen print. A raster file usually has to be redrawn or separated by the art department.")
            asks.append("the original vector file (.ai, .eps or .pdf) with spot colors")
        elif kind == "vector":
            if facts.get("spot_count") == 0 and colors:
                warns.append("No Pantone / spot colors are called out in this file. Screen print inks are matched to PMS colors.")
                asks.append("the PMS (Pantone) colors for each ink")
            if facts.get("color_mode") and "RGB" in facts["color_mode"] and "Spot" not in facts["color_mode"]:
                warns.append("RGB file — colors will shift when matched to inks.")
            if facts.get("has_gradients"):
                warns.append("Gradients print as halftones (a dot pattern), not a smooth blend.")
            if facts.get("hairlines"):
                warns.append("Hairline strokes (under 0.5 pt) may not hold on a screen.")
            if colors:
                notes.append(f"{colors} color{'s' if colors != 1 else ''} detected = {colors} screen{'s' if colors != 1 else ''}. Price goes up with each ink color.")
        notes.append("A white underbase is used by default on colored garments.")
        confirm.append("The garment is not layered (screen print needs a flat, non-layered surface).")

    elif method_key == "embroidery":
        if kind == "embroidery":
            if facts.get("stitch_count"):
                notes.append(f"{facts['stitch_count']:,} stitches" + (f", {facts['thread_colors']} thread color(s)." if facts.get("thread_colors") else "."))
            notes.append("Supplied stitch files (.dst and similar) are accepted and kept on file.")
        else:
            if facts.get("has_gradients"):
                fails.append("Gradients can't be stitched as a smooth blend. The art needs a solid-color version for embroidery.")
                asks.append("a version of the logo in solid colors, without gradients or shading")
            if facts.get("hairlines"):
                warns.append("Hairline strokes (under 0.5 pt) are too thin to stitch.")
            if colors:
                notes.append(f"{colors} color{'s' if colors != 1 else ''} detected = {colors} thread color{'s' if colors != 1 else ''}.")
            notes.append("This art will need to be digitized. The exact stitch count is only known after digitizing.")
        confirm.append('The smallest text will be at least 3/16" tall at the final size.')

    elif method_key == "dtfx":
        if facts.get("soft_alpha"):
            warns.append("This art appears to have fades or see-through areas. DTFx needs solid edges — fades and transparency are not allowed.")
            asks.append("a version with solid edges and no fades to transparent")
        if is_raster and facts.get("has_alpha") is False:
            warns.append("No transparent background — the background (including white) will print as part of the design.")
            asks.append("a PNG with a transparent background, or the vector file")
        if facts.get("has_gradients"):
            confirm.append("Any gradient blends between solid colors and does not fade out to nothing.")
        confirm.append("The smallest detail is at least 1 mm (about 4 pt type) at the final size.")

    elif method_key == "dtg":
        if is_raster and facts.get("has_alpha") is False:
            warns.append("No transparent background — the background (including white) will print as part of the design.")
            asks.append("a PNG with a transparent background, or the vector file")
        mode = facts.get("color_mode") or ""
        if "CMYK" in mode:
            notes.append("RGB files are recommended for digital print — they translate to the printer's inks more accurately than CMYK.")
        if kind == "vector":
            notes.append("Vector art is recommended for digital print because it can be resized to any size.")
        confirm.append("The garment is 100% cotton (50/50 blends print duller and more faded).")

    elif method_key == "dye_sub":
        notes.append("Sublimation has no white ink: anything white in the art will show the garment color.")
        confirm.append("The garment is white 100% polyester (blends and colored garments look faded).")

    elif method_key == "laser_etch":
        if colors and colors > 1:
            warns.append(f"Laser etch is tone-on-tone (one shade). This {colors}-color art will be converted to a single color.")
            asks.append("a one-color version of the logo")
        if facts.get("has_gradients"):
            warns.append("Gradients and shading don't reproduce in laser etch.")
        if rasterish:
            warns.append("Vector art works best for laser etch. A raster file may need to be redrawn.")
            asks.append("the original vector file (.ai, .eps or .pdf)")
        if facts.get("hairlines"):
            warns.append("Hairline strokes (under 0.5 pt) may not show.")
        confirm.append("The garment is not cotton, and is not white, black, heathered or patterned.")

    elif method_key == "stickers":
        if facts.get("soft_alpha"):
            warns.append("This art appears to have fades or see-through areas. Stickers are printed on vinyl and cut out, so transparency is not possible.")
            asks.append("a version with solid edges and no fades to transparent")
        notes.append('Stickers are cut with a 1/8" offset around the art. A custom cut shape needs a cut line in the file, submitted as a PDF.')

    elif method_key == "buttons":
        notes.append("The imprint is printed with extra bleed so it wraps around the back of the button.")
        confirm.append("The smallest type is at least 6 pt at the final size.")

    elif method_key == "hard_goods":
        notes.append("Hard goods are printed on the decorator's own inventory only, and the maximum imprint depends on the product.")
        confirm.append("The art is set up on the decorator's template for the specific product.")

    # ---- rules for every method
    if facts.get("live_text"):
        warns.append("Fonts are not outlined — see the Font Check.")
        asks.append("the file with all text converted to outlines")
    if (facts.get("page_count") or 1) > 1:
        notes.append(f"Only page 1 of {facts['page_count']} was screened.")
    if method["min_qty"] > 1:
        notes.append(f"Minimum order: {method['min_qty']} pieces.")

    # de-duplicate asks, keep order
    seen, unique_asks = set(), []
    for a in asks:
        if a not in seen:
            seen.add(a)
            unique_asks.append(a)

    verdict = "fail" if fails else ("warn" if warns else "pass")
    return {
        "verdict": verdict, "fails": fails, "warns": warns, "notes": notes, "confirm": confirm,
        "asks": unique_asks, "area": area, "print_size": print_size, "dpi": dpi,
        "method": method_key, "location": location_key,
    }


def customer_script(evaluation):
    """A short 'what to tell your customer' message built from what needs to change."""
    asks = evaluation.get("asks") or []
    if not asks:
        return None
    label = METHODS[evaluation["method"]]["label"]
    if len(asks) == 1:
        return f"To get the best result with {label.lower()}, could you send us {asks[0]}?"
    bullets = "\n".join(f"> - {a}" for a in asks)
    return f"To get the best result with {label.lower()}, could you send us:\n{bullets}"


def artbot_summary(evaluation):
    """One paragraph for ArtBot's file context."""
    label = METHODS[evaluation["method"]]["label"]
    where = ""
    if evaluation.get("location") in LOCATIONS:
        where = f" at {LOCATIONS[evaluation['location']][0]}"
    if evaluation.get("print_size"):
        where += f", print size {_size(*evaluation['print_size'])}"
    verdict = {"pass": "NO PROBLEMS FOUND", "warn": "NEEDS ATTENTION", "fail": "NOT SUITABLE AS-IS"}[evaluation["verdict"]]
    parts = [f"Decoration method check ({GUIDE_NAME} guidelines, general guidance): {label}{where}: {verdict}."]
    if evaluation["fails"]:
        parts.append("Problems: " + " | ".join(evaluation["fails"]))
    if evaluation["warns"]:
        parts.append("Warnings: " + " | ".join(evaluation["warns"]))
    return " ".join(parts)

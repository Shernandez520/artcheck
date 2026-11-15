"""Unit tests for cdr_tools.py (no browser, no Streamlit, no CorelDRAW file needed).

    python tests/test_cdr_tools.py
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cdr_tools  # noqa: E402

NS = "{http://www.w3.org/2000/svg}"

# The shape of what libcdr's cdr2xhtml prints for a two-page CorelDRAW file
LIBCDR_OUTPUT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:svg="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
<body>
<?import namespace="svg" urn="http://www.w3.org/2000/svg"?>
<!--
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
 -->
<svg:svg version="1.1" xmlns:svg="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="11.0000in" height="8.5000in" viewBox="0 0 792.0000 612.0000" >
<svg:g id="Layer1000" >
<svg:path d=" M116,106 L117,106 L117,238 Z" style="fill-rule: evenodd; fill: #ffffff; "/>
</svg:g>
</svg:svg>
<hr/>
<svg:svg version="1.1" xmlns:svg="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="3.0000in" height="2.0000in" viewBox="0 0 216.0000 144.0000" >
<svg:path d=" M0,0 L10,0 L10,10 Z" style="fill: #ff0000; "/>
</svg:svg>
</body>
</html>
"""

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


@case("one SVG document per CorelDRAW page, in order")
def _():
    pages = cdr_tools.svg_pages_from_libcdr(LIBCDR_OUTPUT)
    assert len(pages) == 2
    assert 'width="11.0000in"' in pages[0] and 'width="3.0000in"' in pages[1]


@case("each page is well-formed SVG in the SVG namespace, with no svg: prefixes left")
def _():
    for page in cdr_tools.svg_pages_from_libcdr(LIBCDR_OUTPUT):
        assert "svg:" not in page.replace("xmlns:svg", "")
        root = ET.fromstring(page.encode("utf-8"))
        assert root.tag == NS + "svg", root.tag
        assert root.findall(f".//{NS}path"), "paths were lost"


@case("the HTML wrapper is gone")
def _():
    page = cdr_tools.svg_pages_from_libcdr(LIBCDR_OUTPUT)[0]
    assert "<html" not in page and "<body" not in page and "<hr" not in page


@case("output that is already plain SVG is accepted")
def _():
    plain = '<svg xmlns="http://www.w3.org/2000/svg" width="1in" height="1in"><path d="M0,0 L1,1"/></svg>'
    pages = cdr_tools.svg_pages_from_libcdr(plain)
    assert len(pages) == 1 and ET.fromstring(pages[0].encode("utf-8")).tag == NS + "svg"


@case("plain SVG without a namespace gets one")
def _():
    pages = cdr_tools.svg_pages_from_libcdr('<svg width="1in" height="1in"><path d="M0,0 L1,1"/></svg>')
    assert ET.fromstring(pages[0].encode("utf-8")).tag == NS + "svg"


@case("empty or unrelated output gives no pages")
def _():
    assert cdr_tools.svg_pages_from_libcdr("") == []
    assert cdr_tools.svg_pages_from_libcdr(None) == []
    assert cdr_tools.svg_pages_from_libcdr("<html><body>nothing here</body></html>") == []


if __name__ == "__main__":
    failed = [r for r in RESULTS if not r[1]]
    headline = f"CorelDRAW helpers: {len(RESULTS) - len(failed)} passed, {len(failed)} failed"
    lines = [("✅ " if ok else "❌ ") + name + (f" — {detail}" if detail else "") for name, ok, detail in RESULTS]
    print(headline + "\n" + "\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## {headline}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
    sys.exit(1 if failed else 0)

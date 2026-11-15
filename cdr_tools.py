"""
Helpers for CorelDRAW (.cdr) files. Pure Python, no Streamlit.

libcdr's `cdr2xhtml` does not print a plain SVG. It prints an XHTML page with
one namespace-prefixed drawing per CorelDRAW page:

    <html ...><body> ... <svg:svg width="11.0000in" ...><svg:path .../></svg:svg> ... </body></html>

SVG tools (CairoSVG) reject that wrapper, so the drawings have to be lifted
out and turned into ordinary SVG documents first.
"""
import re

SVG_NS = "http://www.w3.org/2000/svg"


def svg_pages_from_libcdr(xhtml_text):
    """Return one standalone SVG document (str) per CorelDRAW page, in order.

    Returns an empty list when no drawing is found.
    """
    if not xhtml_text:
        return []
    drawings = re.findall(r"<svg:svg\b.*?</svg:svg>", xhtml_text, flags=re.DOTALL)
    prefixed = True
    if not drawings:
        drawings = re.findall(r"<svg\b.*?</svg>", xhtml_text, flags=re.DOTALL)
        prefixed = False

    pages = []
    for drawing in drawings:
        if prefixed:
            drawing = re.sub(r"<(/?)svg:", r"<\1", drawing)
        root_end = drawing.find(">")
        root = drawing[:root_end]
        if f'xmlns="{SVG_NS}"' not in root:
            if f'xmlns:svg="{SVG_NS}"' in root:
                root = root.replace(f'xmlns:svg="{SVG_NS}"', f'xmlns="{SVG_NS}"', 1)
            else:
                root = root.replace("<svg", f'<svg xmlns="{SVG_NS}"', 1)
        pages.append('<?xml version="1.0" encoding="UTF-8"?>\n' + root + drawing[root_end:])
    return pages

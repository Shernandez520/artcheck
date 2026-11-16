"""
ArtCheck - art file screening for promotional products.
Previews, color analysis, font check, decoration method check, vector PDF export
and the ArtBot assistant. See CLAUDE.md for how the pieces fit together.
"""

# Patch Tornado to send server-side WebSocket pings — prevents Railway proxy
# from force-closing connections after its absolute idle/connection limit.
# Must run before Streamlit starts its server, so it goes here at module top.
try:
    import tornado.websocket as _tws
    _orig_get = _tws.WebSocketHandler.get

    async def _ws_get_with_ping(self, *args, **kwargs):
        self.application.settings.setdefault('websocket_ping_interval', 20)
        self.application.settings.setdefault('websocket_ping_timeout', 60)
        return await _orig_get(self, *args, **kwargs)

    _tws.WebSocketHandler.get = _ws_get_with_ping
except Exception:
    pass

import streamlit as st
import subprocess
import os
from PIL import Image, ImageDraw
from pathlib import Path
import html
import tempfile

import decoration_rules  # pure-Python rules for the Decoration Method Check
import io
import cdr_tools         # pure-Python helpers for CorelDRAW conversion
import xcf_tools         # pure-Python GIMP (.xcf) reader
import indd_tools        # reads the thumbnail saved inside InDesign files

# EPS -> PDF conversions made during this script run, keyed by file path. Color
# analysis, the font check and the PDF download all need the same Ghostscript
# conversion; doing it once instead of three times is the EPS speed-up.
_EPS_PDFS = {}


def convert_eps_to_pdf(input_file):
    """EPS -> vector PDF bytes with Ghostscript pdfwrite, or None. Cached per run."""
    if input_file in _EPS_PDFS:
        return _EPS_PDFS[input_file]
    pdf_bytes = None
    out_pdf = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            out_pdf = tmp.name
        base = ['gs', '-dNOPAUSE', '-dBATCH', '-dSAFER', '-sDEVICE=pdfwrite',
                '-dAutoRotatePages=/None', f'-sOutputFile={out_pdf}']
        # -dEPSCrop makes the page the size of the artwork instead of a letter page
        for extra in (['-dEPSCrop'], []):
            run = subprocess.run(base + extra + [input_file], capture_output=True, timeout=30)
            if run.returncode == 0 and os.path.exists(out_pdf) and os.path.getsize(out_pdf) > 0:
                with open(out_pdf, 'rb') as f:
                    pdf_bytes = f.read()
                break
    except Exception:
        pdf_bytes = None
    finally:
        if out_pdf and os.path.exists(out_pdf):
            try:
                os.unlink(out_pdf)
            except Exception:
                pass
    _EPS_PDFS[input_file] = pdf_bytes
    return pdf_bytes


def mixed_label(label, image_count):
    """'Vector (EPS)' -> 'Vector + raster (EPS)' when the file also holds pictures.
    A file can be vector by format and still carry raster images; the label should
    not promise more than the file delivers. (Never use the words "embedded raster"
    here: that label means the file is ONLY a picture and switches the rules.)"""
    if image_count and label.startswith('Vector ('):
        return 'Vector + raster (' + label[len('Vector ('):]
    return label


def effective_suffix(filename, data):
    """The file type to process an upload as.

    Illustrator can save an .ai file in its older PostScript form (it starts with
    "%!PS-Adobe ... EPSF", common for stock art) instead of the usual PDF form. Such
    a file is an EPS in everything but name, so it goes down the EPS path.
    """
    suffix = Path(filename).suffix.lower()
    if suffix == '.ai':
        head = bytes(data[:64]).lstrip()
        if head.startswith(b'%!PS') or head.startswith(b'\xc5\xd0\xd3\xc6'):
            return '.eps'
    return suffix


def flatten_gimp_upload(data, upload_id):
    """Flatten a GIMP (.xcf) upload once: full-size PNG, a lighter copy to show, and
    the same analysis any other image gets. Returns {'id', 'error'} when it can't."""
    try:
        flat = xcf_tools.flatten(data)
    except xcf_tools.XcfError as err:
        return {'id': upload_id, 'error': str(err)}
    except Exception:
        return {'id': upload_id, 'error': "GIMP (.xcf) file could not be read."}
    image = flat.pop('image')
    dpi = flat.get('dpi') or (72.0, 72.0)
    full = io.BytesIO()
    image.save(full, format='PNG', dpi=dpi, compress_level=3)
    png = full.getvalue()
    shown = image
    if max(image.size) > 1600:
        shown = image.copy()
        shown.thumbnail((1600, 1600), Image.LANCZOS)
    small = io.BytesIO()
    shown.save(small, format='PNG')
    del image, shown
    with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
        tmp.write(png)
        tmp_path = tmp.name
    try:
        analysis = RasterAnalyzer().analyze(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return {'id': upload_id, 'error': None, 'png': png, 'display': small.getvalue(),
            'analysis': analysis, 'info': flat}


class _LazyPdf:
    """An uploaded PDF / AI that is only opened if something actually needs it.

    The page count and "is this page just a picture?" answers are remembered in
    session state, so on most clicks the file is never opened at all.
    """

    def __init__(self, uploaded):
        self._uploaded = uploaded
        self._doc = None

    def doc(self):
        if self._doc is None:
            import fitz
            self._doc = fitz.open(stream=self._uploaded.getvalue(), filetype="pdf")
        return self._doc

    def close(self):
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None


def extract_pdf_page(input_file, page_index):
    """Write ONE page of a PDF / AI file to a new temp file and return its path.

    The whole analysis pipeline (preview, size, colors, fonts, raster detection)
    works on page 1 of whatever file it is given, so handing it a one-page copy
    makes every part of it page-specific without touching the analyzers.
    Returns None if the page can't be extracted.
    """
    out_path = None
    try:
        import fitz
        src = fitz.open(input_file)
        try:
            if page_index < 0 or page_index >= src.page_count:
                return None
            single = fitz.open()
            single.insert_pdf(src, from_page=page_index, to_page=page_index)
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(input_file).suffix) as tmp:
                out_path = tmp.name
            single.save(out_path, garbage=3, deflate=True)
            single.close()
        finally:
            src.close()
        return out_path
    except Exception:
        if out_path and os.path.exists(out_path):
            os.unlink(out_path)
        return None


def compose_background(img, bg_type):
    """Put a transparent preview on the chosen background and return the new image.

    bg_type: 'auto' | 'light' | 'dark' | 'transparent' (checkerboard) |
             'transparent_alpha' (leave the transparency alone).
    Used when a preview is generated and again, instantly, whenever the user
    picks a different background — no re-render of the file is needed.
    """
    img = img.convert('RGBA')
    if bg_type == 'transparent_alpha':
        return img

    if bg_type == 'transparent':
        # Classic Photoshop-style checkerboard to show transparency
        checker_size = max(16, min(img.width, img.height) // 30)
        checker = Image.new('RGBA', img.size, (255, 255, 255, 255))
        draw_checker = ImageDraw.Draw(checker)
        light = (204, 204, 204, 255)
        dark_sq = (153, 153, 153, 255)
        for y in range(0, img.height, checker_size):
            for x in range(0, img.width, checker_size):
                color = dark_sq if (x // checker_size + y // checker_size) % 2 == 0 else light
                draw_checker.rectangle([x, y, x+checker_size, y+checker_size], fill=color)
        checker.paste(img, mask=img.split()[3])
        return checker.convert('RGB')

    if bg_type == 'dark':
        bg_color = (30, 30, 30, 255)
    elif bg_type == 'auto':
        # Mostly-light artwork gets a dark background. Measure only the artwork
        # itself: transparent pixels are stored as black, so counting them made a
        # white logo on an empty page look "dark" (white-on-white).
        from PIL import ImageStat
        grayscale = img.convert('L')
        art_mask = img.split()[3].point(lambda a: 255 if a >= 128 else 0)
        stat = ImageStat.Stat(grayscale, mask=art_mask)
        avg = stat.mean[0] if stat.count[0] else 0
        bg_color = (30, 30, 30, 255) if avg > 200 else (255, 255, 255, 255)
    else:  # 'light' and anything unknown
        bg_color = (255, 255, 255, 255)

    background = Image.new('RGBA', img.size, bg_color)
    background.paste(img, mask=img.split()[3])
    return background.convert('RGB')


def compose_preview_bytes(alpha_png_bytes, bg_type):
    """PNG bytes of the stored transparent preview on the chosen background."""
    out = io.BytesIO()
    compose_background(Image.open(io.BytesIO(alpha_png_bytes)), bg_type).save(out, format='PNG')
    return out.getvalue()


# CorelDRAW conversions made during this script run, keyed by file path, so the
# two preview renders and the PDF download share one conversion (it is slow).
# Streamlit re-executes this file on every run, so this never outlives a run.
_CDR_CONVERSIONS = {}


def convert_cdr(input_file):
    """CorelDRAW (.cdr) -> vector PDF, without rasterizing.

    cdr2xhtml (libcdr) -> clean SVG of page 1 (cdr_tools) -> PDF (MuPDF, CairoSVG as fallback).
    Returns {'pdf': bytes, 'pages': page count in the .cdr, 'size_in': (w, h)} or None.
    """
    if input_file in _CDR_CONVERSIONS:
        return _CDR_CONVERSIONS[input_file]
    converted = None
    try:
        run = subprocess.run(["cdr2xhtml", input_file], capture_output=True, timeout=60)
        if run.returncode == 0 and run.stdout:
            pages = cdr_tools.svg_pages_from_libcdr(run.stdout.decode("utf-8", errors="ignore"))
            if pages:
                import fitz
                svg_bytes = pages[0].encode("utf-8")
                pdf_bytes, rect = None, None
                # MuPDF's own SVG reader is about 5x faster than CairoSVG on large
                # drawings and renders the same picture; CairoSVG is the fallback.
                for convert in ("fitz", "cairosvg"):
                    try:
                        if convert == "fitz":
                            svg_doc = fitz.open(stream=svg_bytes, filetype="svg")
                            candidate = svg_doc.convert_to_pdf()
                            svg_doc.close()
                        else:
                            import cairosvg
                            candidate = cairosvg.svg2pdf(bytestring=svg_bytes)
                        doc = fitz.open(stream=candidate, filetype="pdf")
                        page = doc[0]
                        # read_contents() is instant; listing 35,000 paths just to
                        # confirm the page is not empty took most of a second
                        usable = (page.rect.width > 0 and page.rect.height > 0
                                  and len(page.read_contents().strip()) > 0)
                        if usable:
                            pdf_bytes, rect = candidate, page.rect
                        doc.close()
                    except Exception:
                        pass
                    if pdf_bytes:
                        break
                if pdf_bytes and rect.width > 0 and rect.height > 0:
                    converted = {
                        'pdf': pdf_bytes,
                        'pages': len(pages),
                        'size_in': (round(rect.width / 72, 2), round(rect.height / 72, 2)),
                    }
    except Exception:
        converted = None
    _CDR_CONVERSIONS[input_file] = converted
    return converted

# NOTE: GA4 is injected into Streamlit's real index.html <head> by inject_ga.py
# at container startup (see start.sh). Do NOT add gtag via components.html() —
# that renders inside a zero-height iframe, so hits are attributed to the
# iframe's blank document instead of artcheck.app, corrupting analytics.

st.set_page_config(
    page_title="ArtCheck - Preview Generator",
    page_icon="🎨",
    layout="wide"
)

# ============================================================================
# MOCKUP BUILDER ROUTE
# When ?mockup=1 is in the URL, render only the standalone mockup tool.
# Streamlit's static serving sends HTML as text/plain, so we serve through
# components.html() instead.
# ============================================================================
# ============================================================================
# MOCKUP BUILDER HANDOFF STORE
# Cross-session dict for passing artwork from analysis tab to mockup tab.
# @st.cache_resource keeps the dict alive across reruns and sessions —
# module-level state alone gets wiped each rerun.
# Tokens are single-use; entries auto-expire after 5 minutes.
# ============================================================================
@st.cache_resource
def _get_mockup_handoff_store():
    return {}

def _cleanup_mockup_handoff():
    """Drop handoff entries older than 5 minutes."""
    import time as _time
    _store = _get_mockup_handoff_store()
    _now = _time.time()
    _stale = [_k for _k, _v in _store.items() if _now - _v[2] > 300]
    for _k in _stale:
        _store.pop(_k, None)


def _render_mockup_builder_button(art_bytes, filename_stem):
    """Mint a handoff token for the given artwork bytes and render the
    'Open Mockup Builder' button. Used by both vector and raster flows."""
    import secrets as _secrets, time as _time
    if not art_bytes:
        return
    _store = _get_mockup_handoff_store()
    _existing_token = st.session_state.get('mockup_handoff_token')
    # Reuse the token only if it still holds THIS artwork. Otherwise a token
    # minted for a previous file would open the Mockup Builder with the old art.
    if _existing_token and _existing_token in _store and _store[_existing_token][0] != art_bytes:
        _store.pop(_existing_token, None)
        _existing_token = None
    if _existing_token and _existing_token in _store:
        _b, _n, _ = _store[_existing_token]
        _store[_existing_token] = (_b, _n, _time.time())
        _mockup_token = _existing_token
    else:
        _mockup_token = _secrets.token_urlsafe(8)
        _art_filename = f"{filename_stem}_preview.png"
        _store[_mockup_token] = (art_bytes, _art_filename, _time.time())
        st.session_state['mockup_handoff_token'] = _mockup_token
    _cleanup_mockup_handoff()
    st.markdown(
        f'<a href="?mockup=1&token={_mockup_token}" target="_blank" '
        'style="display:block;text-align:center;padding:0.6rem 1rem;margin-top:0.5rem;'
        'background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);'
        'color:white;text-decoration:none;border-radius:6px;font-weight:600;'
        'font-size:0.95rem;">'
        '🖼️ Open Mockup Builder →</a>'
        '<div style="font-size:0.78rem;color:#888;text-align:center;margin-top:6px;">'
        'Your artwork will be pre-loaded — just drop in a product photo</div>',
        unsafe_allow_html=True
    )


if st.query_params.get("mockup"):
    import streamlit.components.v1 as _mockup_components
    import base64 as _b64
    try:
        with open("static/mockup.html", "r", encoding="utf-8") as _mf:
            _mockup_html = _mf.read()

        # Preload artwork if a valid token was passed
        _token = st.query_params.get("token", "")
        _store = _get_mockup_handoff_store()
        if _token and _token in _store:
            _art_bytes, _art_name, _ = _store.pop(_token)
            _b64_data = _b64.b64encode(_art_bytes).decode("ascii")
            import json as _json
            # json.dumps quotes and escapes the name; "<" is escaped as well so a
            # file name can never close the script tag
            _safe_name = _json.dumps(str(_art_name)).replace("<", "\\u003c")
            _inject = (
                f'<script>'
                f'window.__preloadedArtwork = "data:image/png;base64,{_b64_data}";'
                f'window.__preloadedArtworkName = {_safe_name};'
                f'</script>'
            )
            _mockup_html = _mockup_html.replace("</head>", _inject + "</head>", 1)

        # Hide Streamlit's default chrome on this page only
        st.markdown("""
        <style>
            [data-testid="stHeader"], [data-testid="stToolbar"],
            [data-testid="stDecoration"], footer, #MainMenu { display: none !important; }
            .block-container { padding: 0 !important; max-width: 100% !important; }
            section.main > div { padding: 0 !important; }
        </style>
        """, unsafe_allow_html=True)
        _mockup_components.html(_mockup_html, height=1400, scrolling=True)
    except Exception as _err:
        st.error(f"Could not load Mockup Builder: {_err}")
    st.stop()

# The sun / moon button. It runs in a small frame of its own and reaches into the
# page (same origin):
# - Streamlit keeps the visitor's theme in localStorage under stActiveTheme-<path>-v1
#   and switches without a reload when it receives the SET_CUSTOM_THEME_CONFIG
#   message its hosting platform uses. That message is only accepted from
#   Streamlit's own hosts, so the event is created here with one of those origins.
#   This relies on Streamlit 1.43 internals; the version is pinned and
#   tests/e2e_test.py fails if it stops working.
# - <html data-ac-theme="light|dark"> is what ArtCheck's own CSS keys on.
# - Dark is the default: a first-time visitor is switched to dark, whatever their
#   computer is set to. Their own choice is remembered by the browser.
THEME_TOGGLE_HTML = """
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent;overflow:hidden;}
button{width:40px;height:40px;border-radius:10px;cursor:pointer;font-size:19px;line-height:1;
       border:1px solid rgba(250,250,250,0.22);background:rgba(250,250,250,0.06);padding:0;}
button:hover{background:rgba(250,250,250,0.14);}
html[data-theme="light"] button{border-color:rgba(49,51,63,0.25);background:rgba(49,51,63,0.05);}
html[data-theme="light"] button:hover{background:rgba(49,51,63,0.12);}
</style></head><body>
<button id="t" type="button" title="Switch between light and dark" aria-label="Switch between light and dark">🌙</button>
<script>
(function(){
  var P = window.parent, root = P.document.documentElement, btn = document.getElementById('t');
  var KEY = 'stActiveTheme-' + P.location.pathname + '-v1';
  function saved(){ try { return (JSON.parse(P.localStorage.getItem(KEY)) || {}).name; } catch (e) { return null; } }
  function send(name){
    P.dispatchEvent(new P.MessageEvent('message', {
      data: {stCommVersion: 1, type: 'SET_CUSTOM_THEME_CONFIG', themeName: name},
      origin: 'https://share.streamlit.io'}));
  }
  function show(name){
    var t = name === 'Light' ? 'light' : 'dark';
    root.setAttribute('data-ac-theme', t);
    document.documentElement.setAttribute('data-theme', t);
    btn.textContent = t === 'light' ? '☀️' : '🌙';
  }
  var name = saved();
  if (name !== 'Light' && name !== 'Dark') { name = 'Dark'; send('Dark'); }
  show(name);
  btn.addEventListener('click', function(){
    var next = root.getAttribute('data-ac-theme') === 'light' ? 'Dark' : 'Light';
    send(next); show(next);
  });
  // stay in step if the theme is changed from Streamlit's own settings menu
  setInterval(function(){ var n = saved(); if (n === 'Light' || n === 'Dark') show(n); }, 1500);
})();
</script></body></html>
"""

# Custom CSS
st.markdown("""
<style>
    /* ArtCheck's own colors, dark by default; <html data-ac-theme> is set by the sun / moon button */
    :root {
        --ac-tagline: #ccc; --ac-tip: #9cb4d8; --ac-rule: #333; --ac-muted: #aaa;
        --ac-card-bg: #1a2535; --ac-card-title: #fff; --ac-card-text: #b0c4de;
        --ac-card-accent: #a0d0b0; --ac-card-sub: #a0b8d0; --ac-card-hint: #556a7a;
        --ac-warn-bg: #2a1f1f; --ac-warn-text: #ccc; --ac-warn-strong: #ff9999;
    }
    :root[data-ac-theme="light"] {
        --ac-tagline: #4a4f5c; --ac-tip: #3b558f; --ac-rule: #d5d8e0; --ac-muted: #666;
        --ac-card-bg: #e4ebf8; --ac-card-title: #16233a; --ac-card-text: #33435e;
        --ac-card-accent: #1f7a43; --ac-card-sub: #3a5578; --ac-card-hint: #62738a;
        --ac-warn-bg: #fbeaea; --ac-warn-text: #4a2a2a; --ac-warn-strong: #b3261e;
    }
    .st-key-theme_toggle {
        position: absolute; top: 0.25rem; right: 0; width: 44px; z-index: 20;
    }
    .success-box {
        padding: 1.5rem;
        border-radius: 0.5rem;
        background: #d4edda;
        border: 3px solid #28a745;
        margin: 1rem 0;
        color: #155724;
        font-size: 1.1rem;
        font-weight: bold;
    }
    section[data-testid="stSidebar"] * {
        font-size: 0.95rem !important;
    }
    section[data-testid="stSidebar"] .stButton button {
        font-size: 0.95rem !important;
    }
    section[data-testid="stSidebar"] .stTextInput input {
        font-size: 0.95rem !important;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# ARTBOT INTEGRATION
# ============================================================================

ARTBOT_SYSTEM_PROMPT = """You are ArtBot, a senior production artist with 20+ years of promotional products experience. You're like the veteran art department lead who sales reps message when they have a customer issue.

YOUR ROLE: Give sales reps EXACTLY what to say/do - not just technical info. You're their experienced colleague who's handled this situation 1,000 times before.

CRITICAL PRINCIPLE - TECHNICAL ACCURACY WITH COMMERCIAL REALITY:
Always be technically accurate (customers can Google/ask ChatGPT to verify), BUT frame answers around commercial practicality for promotional products vendors. Use this pattern: "YES, [X] is technically possible, BUT here's why most vendors don't offer it / here's the commercial reality / here's what actually works better in production."

Never say something CAN'T be done if it technically can - instead explain why it's not commonly offered and provide practical alternatives.

RESPONSE STRUCTURE - ALWAYS include these sections when relevant:

1. 📋 QUICK ANSWER (what's happening - be technically accurate)
2. 📧 CUSTOMER SCRIPT (exact words to use)
3. 💡 HOW TO EXPLAIN IT (customer-friendly language)
4. 🔍 WHAT TO CHECK (troubleshooting steps)
5. 💰 PRICING GUIDANCE (how to handle costs)
6. ⚠️ RED FLAGS (what to watch for)

CORE EXPERTISE:
- File format requirements for all decoration methods (screen printing, embroidery, DTG, laser engraving, pad printing, debossing, etc.)
- Vector vs raster - and how to explain this to customers who don't care about technical details
- Color management: Pantone matching, CMYK vs RGB, spot colors, and why "it looks different on my screen"
- Resolution requirements and how to handle low-res files
- File preparation issues and what causes art department rejections
- Embroidery specifics: stitch counts, thread colors, digitizing
- Screen printing: color separations, underbase, limitations
- Common customer objections and how to address them

DECORATION METHODS & CUSTOMER-FACING LANGUAGE:

Screen Printing:
- Tech: PMS spot colors, halftones for gradients, underbase on colored garments. Each color is a separate screen and adds cost; the maximum number of colors varies by decorator
- Customer: "Each color is a separate screen, which affects pricing. Complex designs with many colors work better with other methods."

Embroidery:
- Tech: Stitch files (.dst, .pes) or digitizing from art. Stitch count drives price and is only known after digitizing; limits vary by decorator. Smallest text about 3/16" tall. Gradients can't be stitched as smooth blends
- Customer: "Your logo needs to be converted to stitch data. More complex designs have higher stitch counts which increase cost and can cause fabric puckering."

DTG (Direct-to-Garment):
- Tech: Full color, vector or raster. Raster needs at least 200 DPI at print size (300 DPI recommended). RGB preferred. White underbase on dark garments
- Customer: "This prints like an inkjet printer directly on the shirt. Great for photos and complex designs, but works best on cotton and light colors."

PHOTOSHOP FILES: Do not say Photoshop fonts are "already rasterized." A layered .psd can still contain live, editable text layers that need the font installed. Text is only locked in once the file is flattened or exported (PNG, JPG, TIFF, flattened PDF). For Photoshop art, tell the rep to ask for a flattened export at full resolution, or to rasterize the type layers first.

CONSISTENCY WITH ARTCHECK: Specs vary by decorator. ArtCheck's Decoration Method Check uses Dubow Textile's published guidelines as a general guide. If the file context includes a decoration method check result, stay consistent with its numbers and verdict, and remind the rep to confirm specifics with their own decorator.

CRITICAL: Frame technical issues as protecting the customer's brand quality, not as limitations.

Bad: "Your file won't work"
Good: "To ensure your logo looks sharp and professional on the final product, we need..."

HANDLING "BUT CHATGPT SAID..." SCENARIOS:
If a customer claims ChatGPT or Google says something is possible that you're recommending against, acknowledge the technical possibility FIRST, then explain the commercial reality. Never contradict easily verifiable information - instead add the context ChatGPT doesn't have (industry pricing, vendor capabilities, production practicalities).

COMMUNICATION STYLE:
- Lead with the customer-facing script - that's what the rep needs immediately
- Use "Here's what to tell them:" before scripts
- Include pricing guidance (reps need to know if they can negotiate)
- Give the "why" in customer-friendly language (not technical jargon)
- Point out upsell opportunities when relevant
- Warn about common customer objections

AVOID:
- Don't just say "they need 300 DPI" - give them the WORDS to explain why
- Don't give tech specs without context about impact on timeline/cost
- Don't assume the sales rep knows how to handle pushback
- Don't leave pricing ambiguous - give ranges or tell them to check with production

Remember: You're not just answering technical questions - you're coaching sales reps through customer conversations. Give them confidence, scripts, and the reasoning to back it up."""

# ============================================================================
# ORIGINAL ARTCHECK CODE (Embroidery + Vector handling)
# ============================================================================

class EmbroideryConverter:
    """Handles embroidery file conversion to PNG"""
    
    EMBROIDERY_FORMATS = ['.dst', '.pes', '.exp', '.jef', '.vp3', '.xxx', '.u01']
    
    def __init__(self):
        try:
            import pyembroidery
            self.pyembroidery = pyembroidery
            self.available = True
        except ImportError:
            self.pyembroidery = None
            self.available = False
    
    def is_embroidery_file(self, filename):
        """Check if file is an embroidery format"""
        return Path(filename).suffix.lower() in self.EMBROIDERY_FORMATS

    def get_thread_colors(self, pattern):
        """
        Extract thread colors from embroidery pattern.
        PES files carry real color data; DST and others may return black defaults.
        Returns (colors_list, unique_count)
        """
        colors = []
        seen = set()
        for thread in pattern.threadlist:
            argb = thread.color
            r = (argb >> 16) & 0xFF
            g = (argb >> 8) & 0xFF
            b = argb & 0xFF
            hex_color = f"#{r:02X}{g:02X}{b:02X}"
            colors.append({
                "hex": hex_color,
                "rgb": (r, g, b),
                "is_duplicate": hex_color in seen,
            })
            seen.add(hex_color)
        unique_count = len(set(c["hex"] for c in colors))
        return colors, unique_count
    
    def convert_to_png(self, input_file, output_file, width=1200, height=800):
        """Convert embroidery file to PNG visualization"""
        if not self.available:
            return False, "pyembroidery not installed"
        
        try:
            # Read embroidery file
            pattern = self.pyembroidery.read(str(input_file))
            
            # Transparent canvas, so the background buttons work for stitch files too
            img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Get pattern bounds
            bounds = pattern.bounds()
            if not bounds or len(bounds) != 4:
                return False, "Could not determine pattern bounds"
            
            min_x, min_y, max_x, max_y = bounds
            
            # Calculate scaling
            pattern_width = max_x - min_x
            pattern_height = max_y - min_y
            
            if pattern_width == 0 or pattern_height == 0:
                return False, "Pattern has zero dimensions"
            
            # Add margins
            margin = 50
            scale_x = (width - 2 * margin) / pattern_width
            scale_y = (height - 2 * margin) / pattern_height
            scale = min(scale_x, scale_y)
            
            # Center the pattern
            offset_x = margin + (width - 2 * margin - pattern_width * scale) / 2
            offset_y = margin + (height - 2 * margin - pattern_height * scale) / 2
            
            # pyembroidery commands are VALUES in the low byte (STITCH 0, JUMP 1, TRIM 2,
            # STOP 3, END 4, COLOR_CHANGE 5), not bit flags. Testing them with "&" made
            # every jump count as a thread change.
            pe = self.pyembroidery
            mask = getattr(pe, 'COMMAND_MASK', 0xFF)
            thread_colors, unique_color_count = self.get_thread_colors(pattern)

            def thread_rgba(index):
                # Files without color data (most .dst) are drawn black
                if 0 <= index < len(thread_colors):
                    return thread_colors[index]['rgb'] + (255,)
                return (0, 0, 0, 255)

            prev = None
            color_index = 0
            current_color = thread_rgba(0)
            stitch_count = 0
            thread_changes = 0
            for stitch in pattern.stitches:
                command = (stitch[2] if len(stitch) > 2 else pe.STITCH) & mask
                point = (offset_x + (stitch[0] - min_x) * scale, offset_y + (stitch[1] - min_y) * scale)
                if command == pe.STITCH:
                    stitch_count += 1
                    if prev is not None:
                        draw.line([prev, point], fill=current_color, width=2)
                    prev = point
                elif command == pe.COLOR_CHANGE:
                    thread_changes += 1
                    color_index += 1
                    current_color = thread_rgba(color_index)
                    prev = None
                elif command == pe.JUMP:
                    prev = point          # the needle moves without sewing
                else:                     # TRIM, STOP, END and anything else: thread is cut
                    prev = None
            
            # Save image
            img.save(output_file, 'PNG')


            return True, {
                'stitch_count': stitch_count,
                'thread_changes': thread_changes,
                'width_mm': round(pattern_width / 10, 2),  # Convert to mm
                'height_mm': round(pattern_height / 10, 2),
                'thread_colors': thread_colors,
                'unique_color_count': unique_color_count,
            }
            
        except Exception as e:
            return False, f"Conversion error: {str(e)}"


class PreviewGenerator:
    """Handles conversion of vector files to PNG previews - CLOUD OPTIMIZED"""
    
    PREVIEW_MAX_WIDTH = 1200
    # Longest side, in pixels, of a fitz render. Without a cap a letter-size
    # page renders at 6120x7920 (~700 MB peak) and a poster cannot render at all.
    # 4000 px keeps pages up to ~13" at 300+ DPI; small artwork is unaffected.
    RENDER_MAX_PX = 4000
    
    def __init__(self):
        self.embroidery = EmbroideryConverter()
        # Heavy libraries (cairosvg, fitz, pdf2image) are imported lazily
        # inside each conversion method to minimize memory at idle
    
    def _svg_has_embedded_raster(self, input_file):
        """Detect if SVG is just a wrapper around an embedded raster image"""
        try:
            with open(input_file, 'r', errors='ignore') as f:
                content = f.read(4000)  # Check first 4KB
            # SVGs with embedded rasters typically have base64 image data or xlink:href to raster
            import re
            has_image_tag = bool(re.search(r'<image', content, re.IGNORECASE))
            has_base64 = 'base64' in content
            # Check if there are almost no path/shape elements (pure raster wrapper)
            has_paths = bool(re.search(r'<(path|rect|circle|ellipse|line|polyline|polygon)', content, re.IGNORECASE))
            return has_image_tag and (has_base64 or not has_paths)
        except Exception:
            return False

    def _pdf_has_only_raster(self, input_file):
        """Detect if a PDF contains only raster images with no vector paths"""
        try:
            import fitz
            doc = fitz.open(input_file)
            vector_path_count = 0
            raster_image_count = 0
            for page in doc:
                # Count vector paths
                paths = page.get_cdrawings()     # same list as get_drawings(), half the time
                vector_path_count += len(paths)
                # Count raster images
                images = page.get_images()
                raster_image_count += len(images)
            doc.close()
            # If there are images and very few or no vector paths, it's raster-in-PDF
            if raster_image_count > 0 and vector_path_count < 3:
                return True, raster_image_count
            return False, 0
        except Exception:
            return False, 0

    def _pdf_page_size_inches(self, input_file):
        """Real document size of page 1 in inches (PDF points / 72).
        The preview is rendered at a variable scale, so pixels / 300 is NOT
        the physical size for PDF/AI files. Returns (w_in, h_in) or None."""
        try:
            import fitz
            doc = fitz.open(input_file)
            rect = doc[0].rect
            doc.close()
            if rect.width > 0 and rect.height > 0:
                return round(rect.width / 72, 2), round(rect.height / 72, 2)
        except Exception:
            pass
        return None

    def _pdf_page_count(self, input_file):
        """Number of pages (or Illustrator artboards) in a PDF/AI file."""
        try:
            import fitz
            doc = fitz.open(input_file)
            count = doc.page_count
            doc.close()
            return count
        except Exception:
            return 1

    def _svg_size_inches(self, input_file):
        """Physical size of an SVG, only when the file states one in real-world
        units (in, mm, cm, pt, pc). Pixel or unitless sizes are not a print
        size (apps disagree on pixels per inch), so those return None."""
        try:
            import re
            with open(input_file, 'r', errors='ignore') as f:
                head = f.read(20000)
            root = re.search(r'<svg\b[^>]*>', head, re.IGNORECASE | re.DOTALL)
            if not root:
                return None
            per_inch = {'in': 1.0, 'mm': 25.4, 'cm': 2.54, 'pt': 72.0, 'pc': 6.0}
            sizes = []
            for attr in ('width', 'height'):
                m = re.search(r'(?<![-\w])' + attr + r'\s*=\s*["\']\s*([0-9]*\.?[0-9]+)\s*(in|mm|cm|pt|pc)\s*["\']',
                              root.group(0), re.IGNORECASE)
                if not m:
                    return None
                inches = float(m.group(1)) / per_inch[m.group(2).lower()]
                if inches <= 0:
                    return None
                sizes.append(round(inches, 2))
            return sizes[0], sizes[1]
        except Exception:
            return None

    def _convert_svg_with_cairosvg(self, input_file, output_file):
        """Convert SVG to PNG using CairoSVG"""
        try:
            import cairosvg
        except ImportError:
            return False
        try:
            with open(input_file, 'rb') as f:
                svg_content = f.read()
            cairosvg.svg2png(
                bytestring=svg_content,
                write_to=output_file,
                output_width=self.PREVIEW_MAX_WIDTH
            )
            return os.path.exists(output_file) and os.path.getsize(output_file) > 0
        except Exception:
            return False

    def _eps_render_dpi(self, input_file):
        """300 dpi, or less when the artwork is so large that 300 dpi would pass
        RENDER_MAX_PX (a 64" x 28" EPS is 160 million pixels at 300 dpi).
        Returns (dpi, (width_pt, height_pt) or None)."""
        import re
        try:
            with open(input_file, 'rb') as f:
                head = f.read(65536)
                f.seek(max(0, os.path.getsize(input_file) - 8192))
                tail = f.read()
            box = None
            for chunk in (head, tail):
                for key in (rb'%%HiResBoundingBox:', rb'%%BoundingBox:'):
                    m = re.search(key + rb'\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)', chunk)
                    if m:
                        x0, y0, x1, y1 = (float(v) for v in m.groups())
                        if x1 > x0 and y1 > y0:
                            box = (x1 - x0, y1 - y0)
                            break
                if box:
                    break
            if not box:
                return 300, None
            longest_px = max(box) / 72 * 300
            if longest_px <= self.RENDER_MAX_PX:
                return 300, box
            return max(10, int(self.RENDER_MAX_PX * 72 / max(box) * 100) / 100), box
        except Exception:
            return 300, None

    def _convert_eps_with_ghostscript(self, input_file, output_file):
        """Convert EPS to PNG using Ghostscript"""
        dpi, self._eps_box_pt = self._eps_render_dpi(input_file)
        self._eps_dpi = dpi
        try:
            cmd = [
                'gs', '-dNOPAUSE', '-dBATCH', '-dSAFER',
                '-sDEVICE=pngalpha',
                f'-r{dpi}',
                '-dEPSCrop',
                f'-sOutputFile={output_file}',
                input_file
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                return True
            # Try without EPSCrop if that failed
            cmd2 = [
                'gs', '-dNOPAUSE', '-dBATCH', '-dSAFER',
                '-sDEVICE=pngalpha',
                f'-r{dpi}',
                f'-sOutputFile={output_file}',
                input_file
            ]
            result2 = subprocess.run(cmd2, capture_output=True, timeout=30)
            return result2.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0
        except Exception as e:
            st.warning(f"Ghostscript EPS conversion failed: {str(e)}")
            return False

    def _convert_with_fitz(self, input_file, output_file):
        """Convert PDF or SVG to PNG using PyMuPDF (fitz) - handles AI-native PDFs"""
        try:
            import fitz
        except ImportError:
            return False
        try:
            doc = fitz.open(input_file)
            page = doc[0]
            rect = page.rect
            longest = max(rect.width, rect.height)
            scale = max(10, 1200 / longest)
            # Cap large pages so the render can't exhaust server memory
            scale = min(scale, self.RENDER_MAX_PX / longest)
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=True)
            pix.save(output_file)
            doc.close()
            return os.path.exists(output_file) and os.path.getsize(output_file) > 0
        except Exception:
            return False

    def _apply_background(self, output_file, bg_type):
        """Apply a background to a PNG preview file (see compose_background)."""
        try:
            compose_background(Image.open(output_file), bg_type).save(output_file, 'PNG')
        except Exception as e:
            st.warning(f"Background application failed: {str(e)}")

    def _convert_cdr(self, input_file, output_file):
        """Convert CorelDRAW .cdr to PNG.

        convert_cdr() makes a vector PDF of page 1, rendered here with fitz
        (correct page size, transparency, render cap).
        """
        converted = convert_cdr(input_file)
        if converted:
            pdf_tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as pdf_tmp:
                    pdf_tmp.write(converted['pdf'])
                    pdf_tmp_path = pdf_tmp.name
                if self._convert_with_fitz(pdf_tmp_path, output_file):
                    return True
            except Exception:
                pass
            finally:
                if pdf_tmp_path and os.path.exists(pdf_tmp_path):
                    os.unlink(pdf_tmp_path)
        return False

    def _pdf_image_count(self, input_file):
        """How many raster images sit on page 1 of a PDF / PDF-based .ai."""
        try:
            import fitz
            doc = fitz.open(input_file, filetype="pdf")
            count = len(doc[0].get_images()) if doc.page_count else 0
            doc.close()
            return count
        except Exception:
            return 0

    def _detect_file_type_label(self, input_file, ext):
        """Return accurate file type label"""
        if ext == '.svg' and self._svg_has_embedded_raster(input_file):
            return 'SVG (embedded raster)'
        elif ext == '.eps':
            return 'Vector (EPS)'          # "+ raster" is added after the PDF check, see mixed_label()
        elif ext == '.ai':
            return mixed_label('Vector (AI)', self._pdf_image_count(input_file))
        elif ext == '.pdf':
            is_raster, _ = self._pdf_has_only_raster(input_file)
            if is_raster:
                return 'PDF (embedded raster)'
            return mixed_label('Vector (PDF)', self._pdf_image_count(input_file))
        return 'Vector'

    @staticmethod
    def _new_png_path():
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            return tmp.name

    @staticmethod
    def _discard(path):
        try:
            if path and os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass

    def generate_preview(self, input_file, bg_type='auto'):
        """Generate preview from vector or embroidery file"""
        ext = Path(input_file).suffix.lower()
        
        # Handle embroidery files
        if self.embroidery.is_embroidery_file(input_file):
            output_file = self._new_png_path()
            success, result = self.embroidery.convert_to_png(input_file, output_file)
            
            if success:
                if bg_type != 'transparent_alpha':   # nothing to add: skip a full decode + re-encode
                    self._apply_background(output_file, bg_type)
                img = Image.open(output_file)
                return {
                    'image': output_file,
                    'width': img.width,
                    'height': img.height,
                    'size_kb': round(os.path.getsize(output_file) / 1024, 2),
                    'file_type': 'embroidery',
                    'embroidery_info': result,
                    # Real stitched size, not the size of the preview canvas
                    'width_in': round(result['width_mm'] / 25.4, 2),
                    'height_in': round(result['height_mm'] / 25.4, 2),
                }
            else:
                self._discard(output_file)
                st.error(f"Embroidery conversion failed: {result}")
                return None
        
        output_file = self._new_png_path()
        success = False
        file_type_label = self._detect_file_type_label(input_file, ext)

        if ext == '.eps':
            # EPS: Ghostscript first, then fitz as fallback
            success = self._convert_eps_with_ghostscript(input_file, output_file)
            if not success:
                success = self._convert_with_fitz(input_file, output_file)

        elif ext == '.pdf' or ext == '.ai':
            # PDF/AI: fitz first, pdf2image as fallback
            success = self._convert_with_fitz(input_file, output_file)
            if not success:
                try:
                    from pdf2image import convert_from_path
                    pages = convert_from_path(input_file, first_page=1, last_page=1, dpi=150)
                    if pages:
                        pages[0].save(output_file, 'PNG')
                        success = os.path.exists(output_file) and os.path.getsize(output_file) > 0
                except Exception:
                    pass

        elif ext == '.svg':
            embedded_raster = self._svg_has_embedded_raster(input_file)
            if embedded_raster:
                # Try fitz first for raster-in-SVG, then CairoSVG
                success = self._convert_with_fitz(input_file, output_file)
            if not success:
                success = self._convert_svg_with_cairosvg(input_file, output_file)
            if not success:
                success = self._convert_with_fitz(input_file, output_file)

        elif ext == '.cdr':
            success = self._convert_cdr(input_file, output_file)

        if success and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            if bg_type != 'transparent_alpha':   # nothing to add: skip a full decode + re-encode
                self._apply_background(output_file, bg_type)
            img = Image.open(output_file)
            preview = {
                'image': output_file,
                'width': img.width,
                'height': img.height,
                'size_kb': round(os.path.getsize(output_file) / 1024, 2),
                'file_type': file_type_label
            }
            if ext in ('.pdf', '.ai'):
                size_in = self._pdf_page_size_inches(input_file)
                if size_in:
                    preview['width_in'], preview['height_in'] = size_in
                preview['page_count'] = self._pdf_page_count(input_file)
            elif ext == '.eps' and getattr(self, '_eps_dpi', 300) != 300 and getattr(self, '_eps_box_pt', None):
                # Rendered below 300 dpi to stay under the pixel cap, so pixels / 300
                # would understate the size: report the artwork's own bounding box
                preview['width_in'] = round(self._eps_box_pt[0] / 72, 2)
                preview['height_in'] = round(self._eps_box_pt[1] / 72, 2)
            elif ext == '.svg':
                size_in = self._svg_size_inches(input_file)
                if size_in:
                    preview['width_in'], preview['height_in'] = size_in
                elif 'embedded raster' in file_type_label:
                    preview['size_note'] = 'unknown'
                else:
                    # The preview is always rendered 1200 px wide, so pixels / 300
                    # would report 4" for every SVG
                    preview['size_note'] = 'scalable'
            elif ext == '.cdr':
                converted = convert_cdr(input_file)
                if converted:
                    preview['width_in'], preview['height_in'] = converted['size_in']
                    preview['page_count'] = converted['pages']
                else:
                    preview['size_note'] = 'unknown'
            return preview

        self._discard(output_file)
        # One plain message. (Each renderer used to add its own technical warning,
        # with temp file paths in it.)
        if ext == '.cdr':
            st.error("Could not convert file. ArtCheck could not read this CorelDRAW file. "
                     "Ask for a PDF exported from CorelDRAW and upload that.")
        elif ext == '.ai':
            st.error("Could not convert file. This .ai file may be damaged, or saved without "
                     "“Create PDF Compatible File”. Ask for it to be re-saved from Illustrator with that "
                     "option checked, or exported as PDF.")
        else:
            st.error("Could not convert file. It may be damaged or saved in a way ArtCheck can't read. "
                     "Ask for a fresh export as PDF and upload that.")
        return None



# ============================================================================
# RASTER ANALYZER - Handles PNG/JPG/GIF/TIFF/BMP/WEBP uploads
# ============================================================================

def get_preview_generator():
    return PreviewGenerator()

def get_color_extractor():
    return ColorExtractor()

class RasterAnalyzer:
    """Analyzes raster image files for production suitability"""

    RASTER_FORMATS = ['.png', '.jpg', '.jpeg', '.gif', '.tiff', '.tif', '.bmp', '.webp']

    def is_raster(self, filename):
        return Path(filename).suffix.lower() in self.RASTER_FORMATS

    def analyze(self, input_file):
        """
        Returns dict with:
          width_px, height_px, dpi, color_mode,
          print_sizes, verdict, warnings, recommendations
        """
        results = {
            'width_px': 0, 'height_px': 0,
            'dpi': 72, 'color_mode': 'Unknown',
            'print_sizes': {}, 'verdict': 'unknown',
            'warnings': [], 'recommendations': []
        }
        try:
            img = Image.open(input_file)
            results['width_px'] = img.width
            results['height_px'] = img.height
            results['color_mode'] = img.mode

            # Get DPI from image metadata
            dpi_info = img.info.get('dpi') or img.info.get('jfif_density')
            if dpi_info and isinstance(dpi_info, tuple):
                dpi = round(max(dpi_info[0], dpi_info[1]))
            elif dpi_info and isinstance(dpi_info, (int, float)):
                dpi = round(dpi_info)
            else:
                dpi = 72  # Default assumption for web images

            # Clamp to realistic range
            if dpi < 1 or dpi > 2400:
                dpi = 72
            results['dpi'] = dpi

            # Calculate usable print sizes
            w_at_300 = round(img.width / 300, 2)
            h_at_300 = round(img.height / 300, 2)
            w_at_150 = round(img.width / 150, 2)
            h_at_150 = round(img.height / 150, 2)
            w_at_200 = round(img.width / 200, 2)
            h_at_200 = round(img.height / 200, 2)

            results['print_sizes'] = {
                '300dpi': (w_at_300, h_at_300),   # Screen print, embroidery digitizing
                '200dpi': (w_at_200, h_at_200),   # Acceptable quality
                '150dpi': (w_at_150, h_at_150),   # DTG minimum
            }

            # Determine production verdict
            max_dim = max(img.width, img.height)
            if dpi >= 300 or (img.width >= 1200 and img.height >= 1200):
                results['verdict'] = 'good'
            elif dpi >= 150 or max_dim >= 800:
                results['verdict'] = 'marginal'
            else:
                results['verdict'] = 'poor'

            # Generate warnings
            # Only warn about low DPI if the image also lacks enough pixels — avoids confusing "72 DPI" 
            # warning on files that are actually fine (high pixel count, just bad metadata)
            if dpi <= 72 and results['verdict'] != 'good':
                results['warnings'].append("⚠️ This file appears to be a low-resolution image, possibly saved from a website or screenshot.")
            if results['verdict'] == 'poor':
                results['warnings'].append("❌ This image is too small to print clearly. It will look blurry or pixelated in production.")
            elif results['verdict'] == 'marginal':
                results['warnings'].append("⚠️ This image may work for small print sizes, but quality isn't guaranteed. Check the print size table below.")

            if img.mode == 'RGB':
                results['warnings'].append("⚠️ This file uses RGB color. That is fine for digital print (DTG), where RGB is recommended, but colors can shift in other print methods.")
            elif img.mode == 'RGBA':
                results['warnings'].append("ℹ️ This image has a transparent background.")
            elif img.mode == 'P':
                results['warnings'].append("⚠️ This file uses a limited color palette, which may affect print quality.")

            # Transparency facts, used by the Decoration Method Check
            try:
                alpha = None
                if img.mode in ('RGBA', 'LA'):
                    alpha = img.getchannel('A')
                elif img.mode == 'P' and 'transparency' in img.info:
                    alpha = img.convert('RGBA').getchannel('A')
                if alpha is None:
                    results['has_transparency'] = False
                    results['soft_transparency'] = False
                else:
                    hist = alpha.histogram()
                    total = sum(hist)
                    visible = total - hist[0]
                    # Any pixel that is not fully opaque
                    results['has_transparency'] = hist[255] < total
                    # Clearly see-through pixels (not just soft anti-aliased edges):
                    # more than 8% of the visible artwork is 10-90% opaque
                    results['soft_transparency'] = bool(visible) and (sum(hist[26:230]) / visible) > 0.08
            except Exception:
                pass

            # Recommendations
            if results['verdict'] in ('poor', 'marginal'):
                results['recommendations'].append("Ask the customer for the original vector file (.ai, .eps, .pdf) from their designer — this is always the best option.")
                results['recommendations'].append("If no vector file exists, ask for the largest/highest-quality version they have (original design file, not a screenshot or download).")
                if dpi <= 72 and results['verdict'] != 'good':
                    results['recommendations'].append("Do not use this file for production — request a replacement from the customer.")
            if img.mode == 'RGB':
                results['recommendations'].append("For print methods other than digital print (DTG), have your art department convert to CMYK or match Pantone colors before production.")

        except Exception as e:
            results['warnings'].append(f"Could not analyze image: {str(e)}")

        return results


def render_raster_results(analysis, filename):
    """Display raster analysis results"""
    verdict = analysis.get('verdict', 'unknown')
    dpi = analysis.get('dpi', 72)
    w, h = analysis.get('width_px', 0), analysis.get('height_px', 0)
    sizes = analysis.get('print_sizes', {})

    # Verdict banner
    if verdict == 'good':
        st.markdown('''<div style="padding:12px;border-radius:8px;background:#1a6b3a;color:#fff;font-size:1rem;font-weight:bold;margin-bottom:12px;">✅ Production Ready — This image has enough detail for printing</div>''', unsafe_allow_html=True)
    elif verdict == 'marginal':
        st.markdown('''<div style="padding:12px;border-radius:8px;background:#7d5a00;color:#fff;font-size:1rem;font-weight:bold;margin-bottom:12px;">⚠️ Borderline Quality — May work for small print sizes only</div>''', unsafe_allow_html=True)
    else:
        st.markdown('''<div style="padding:12px;border-radius:8px;background:#8b1a1a;color:#fff;font-size:1rem;font-weight:bold;margin-bottom:12px;">❌ Not Suitable for Production — Image is too small or low quality</div>''', unsafe_allow_html=True)

    # Image stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Dimensions", f"{w} × {h} px")
    with col2:
        # Show size at 300dpi if metadata DPI is unreliable
        display_dpi = dpi if dpi >= 150 else 300
        w_in = round(w / display_dpi, 2)
        h_in = round(h / display_dpi, 2)
        dpi_label = f"Size @ {display_dpi}dpi" + (" (estimated)" if dpi < 150 else "")
        st.metric(dpi_label, f"{w_in}\" × {h_in}\"")
    with col3:
        st.metric("Color Mode", analysis.get('color_mode', 'Unknown'))

    # Print size table
    if sizes:
        st.markdown("**📐 Usable Print Sizes:**")
        size_300 = sizes.get('300dpi', (0, 0))
        size_200 = sizes.get('200dpi', (0, 0))
        # Same thresholds as the Decoration Method Check (decoration_rules.MIN_DPI / GOOD_DPI)
        st.markdown(f"""
| Quality | DPI | Max Print Size | Use |
|---------|-----|----------------|-----|
| Recommended | 300 | {size_300[0]}" × {size_300[1]}" | Best quality for any print method |
| Minimum | 200 | {size_200[0]}" × {size_200[1]}" | Lowest acceptable for print |
""")
        st.caption("Printing larger than the Minimum size will look soft or pixelated. Pick a method in the Decoration Method Check below to test a specific print size.")

    # Warnings
    if analysis.get('warnings'):
        for w in analysis['warnings']:
            st.warning(w)

    # Recommendations
    if analysis.get('recommendations'):
        st.markdown("**💡 What to do:**")
        for r in analysis['recommendations']:
            st.markdown(f"• {r}")

class ColorExtractor:
    """Extracts fill and stroke colors from vector files before rasterization"""

    def extract(self, input_file):
        """
        Main entry point. Returns dict with:
          fills, strokes, spot_colors, gradients, warnings
        """
        ext = Path(input_file).suffix.lower()
        results = {
            'fills': [],
            'strokes': [],
            'spot_colors': [],
            'gradients': [],
            'warnings': [],
        }

        if ext in ['.pdf', '.ai']:
            return self._extract_from_pdf(input_file, results)
        elif ext == '.eps':
            return self._extract_from_eps(input_file, results)
        elif ext == '.svg':
            return self._extract_from_svg(input_file, results)
        else:
            results['warnings'].append("Color extraction not supported for this file type.")
            return results

    def _cmyk_to_hex(self, c, m, y, k):
        """Convert CMYK (0-1) to hex for display swatch"""
        r = int(255 * (1 - c) * (1 - k))
        g = int(255 * (1 - m) * (1 - k))
        b = int(255 * (1 - y) * (1 - k))
        return f'#{r:02x}{g:02x}{b:02x}', (r, g, b)

    def _rgb_to_hex(self, r, g, b):
        ri, gi, bi = int(r*255), int(g*255), int(b*255)
        return f'#{ri:02x}{gi:02x}{bi:02x}', (ri, gi, bi)

    def _format_cmyk(self, c, m, y, k):
        return f"C:{round(c*100)}% M:{round(m*100)}% Y:{round(y*100)}% K:{round(k*100)}%"

    def _extract_from_pdf(self, input_file, results):
        """Extract colors from PDF/AI using PyMuPDF"""
        try:
            import fitz
            doc = fitz.open(input_file)
            page = doc[0]

            fills = {}
            strokes = {}
            spot_colors = {}
            gradients = []

            # Extract via drawings (paths with fill/stroke info)
            # Detect document color mode
            results['color_mode'] = self._detect_color_mode_pdf(input_file)

            drawings = page.get_drawings()
            for drawing in drawings:
                # Fill color
                if drawing.get('fill') is not None:
                    fill = drawing['fill']
                    fill_cs = drawing.get('fill_opacity', 1.0)
                    opacity = round(fill_cs * 100) if fill_cs <= 1.0 else 100

                    if len(fill) == 4:  # CMYK
                        c, m, y, k = fill
                        label = self._format_cmyk(c, m, y, k)
                        hex_val, rgb = self._cmyk_to_hex(c, m, y, k)
                        key = label
                        if key not in fills:
                            fills[key] = {'label': label, 'hex': hex_val, 'rgb': rgb,
                                         'space': 'CMYK', 'opacity': opacity,
                                         'raw': (c, m, y, k)}
                    elif len(fill) == 3:  # fitz returns RGB for CMYK docs too — skip
                        # RGB fills from fitz are unreliable for production use.
                        # We only store them if we have no better data (handled after loop).
                        r, g, b = fill
                        label = f"R:{round(r*255)} G:{round(g*255)} B:{round(b*255)}"
                        hex_val, rgb_val = self._rgb_to_hex(r, g, b)
                        key = label
                        if key not in fills:
                            fills[key] = {'label': label, 'hex': hex_val, 'rgb': rgb_val,
                                         'space': 'RGB', 'opacity': opacity}
                    elif len(fill) == 1:  # Grayscale
                        gray = fill[0]
                        k_pct = round((1 - gray) * 100)
                        label = f"K:{k_pct}% (Black {k_pct}%)"
                        hex_val, rgb = self._cmyk_to_hex(0, 0, 0, 1-gray)
                        key = label
                        if key not in fills:
                            fills[key] = {'label': label, 'hex': hex_val, 'rgb': rgb,
                                         'space': 'Grayscale', 'opacity': opacity,
                                         'raw': (0, 0, 0, 1-gray)}

                # Stroke color
                if drawing.get('color') is not None:
                    stroke = drawing['color']
                    width = round(drawing.get('width', 1), 2)

                    if len(stroke) == 4:  # CMYK
                        c, m, y, k = stroke
                        label = self._format_cmyk(c, m, y, k)
                        hex_val, rgb = self._cmyk_to_hex(c, m, y, k)
                        key = f"{label}|{width}"
                        if key not in strokes:
                            strokes[key] = {'label': label, 'hex': hex_val, 'rgb': rgb,
                                           'space': 'CMYK', 'width': width,
                                           'raw': (c, m, y, k)}
                    elif len(stroke) == 3:
                        r, g, b = stroke
                        label = f"R:{round(r*255)} G:{round(g*255)} B:{round(b*255)}"
                        hex_val, rgb_val = self._rgb_to_hex(r, g, b)
                        key = f"{label}|{width}"
                        if key not in strokes:
                            strokes[key] = {'label': label, 'hex': hex_val, 'rgb': rgb_val,
                                           'space': 'RGB', 'width': width}
                    elif len(stroke) == 1:
                        gray = stroke[0]
                        k_pct = round((1 - gray) * 100)
                        label = f"K:{k_pct}% (Black {k_pct}%)"
                        hex_val, rgb = self._cmyk_to_hex(0, 0, 0, 1-gray)
                        key = f"{label}|{width}"
                        if key not in strokes:
                            strokes[key] = {'label': label, 'hex': hex_val, 'rgb': rgb,
                                           'space': 'Grayscale', 'width': width}

                # Detect gradients (shading)
                if drawing.get('type') == 'sh':
                    gradients.append({'type': 'gradient', 'label': 'Gradient detected'})

            doc.close()

            # Scan ALL xref objects for spot color / Separation definitions
            # This is where Pantone names live in Illustrator-generated PDFs
            try:
                import re
                doc2 = fitz.open(input_file)
                # (this loop used to call doc2.xref_count(), which does not exist, so it
                # never ran and spot colors were only found by the raw PANTONE scan below)
                def _pdf_name(text):
                    # PDF names write a space as #20: /PANTONE#20289#20C
                    return re.sub(r'#([0-9A-Fa-f]{2})', lambda m: chr(int(m.group(1), 16)), text)
                for xref in range(1, doc2.xref_length()):
                    try:
                        obj_str = doc2.xref_object(xref)
                        if not obj_str or ('Separation' not in obj_str and 'PANTONE' not in obj_str):
                            continue
                        obj_str = _pdf_name(obj_str)
                        # /Separation colorspace with name
                        sep_paren = re.findall(r'/Separation\s*\(([^)]+)\)', obj_str)
                        sep_slash = re.findall(r'/Separation\s*/([^/\[\]<>()\n]+?)\s*(?=/|\[|\d+ \d+ R)', obj_str)
                        for name in sep_paren + sep_slash:
                            name = name.strip()
                            if name and name not in ('All', 'None', 'Black', 'White', 'Cyan', 'Magenta', 'Yellow'):
                                spot_colors[name] = {'label': name, 'type': 'spot'}
                        # Also catch PANTONE anywhere in obj string
                        pantone_hits = re.findall(r'(PANTONE[^/\(\)\[\]<>\n]{1,40})', obj_str)
                        for ph in pantone_hits:
                            ph = re.sub(r'\s+\d+\s+\d+\s+R\b.*$', '', ph)     # "/PANTONE 289 C 3 0 R" in a resource list
                            ph = ph.strip().strip('"-\'')
                            if ph and ph not in spot_colors:
                                spot_colors[ph] = {'label': ph, 'type': 'spot'}
                    except:
                        pass
                doc2.close()
            except:
                pass

            # Fallback: raw byte scan for PANTONE names in case xref missed them
            # AI files often embed Pantone names in compressed PostScript streams
            if not spot_colors:
                try:
                    import re
                    with open(input_file, 'rb') as f:
                        raw = f.read()
                    raw_text = raw.decode('latin-1', errors='ignore')
                    # Match PANTONE names like 'PANTONE 293 U' or 'PANTONE 1235 C'
                    raw_hits = re.findall(r'PANTONE\s+[\w.]+(?:\s+[\w.]+){0,3}', raw_text)
                    seen = set()
                    for hit in raw_hits:
                        hit = hit.strip()
                        # Clean up trailing junk
                        hit = re.sub(r'\s+[a-z]{5,}.*$', '', hit).strip()
                        if hit and hit not in seen and len(hit) < 40:
                            seen.add(hit)
                            spot_colors[hit] = {'label': hit, 'type': 'spot'}
                except:
                    pass

            # Raw decompressed content stream CMYK scan
            # fitz.get_drawings() normalizes colors to RGB, losing CMYK info.
            # Use page.get_contents() which gives decompressed PostScript with real CMYK ops.
            if not spot_colors and not any(v.get('space') == 'CMYK' for v in fills.values()):
                try:
                    import re
                    doc3 = fitz.open(input_file)
                    page3 = doc3[0]
                    # get_contents() returns decompressed stream bytes
                    stream_text = page3.read_contents().decode('latin-1', errors='ignore')
                    doc3.close()

                    cmyk_found = {}
                    painted = self._painted_fill_colors(stream_text)

                    # Illustrator uses 'scn' operator with named colorspace (not 'k')
                    # e.g. /CS0 cs 0 0 0 0.2 scn  or  0 0 0 0.4 scn
                    # Also handle standard 'k' operator for plain CMYK

                    scn_hits = self._cmyk_operands(stream_text, 'scn')

                    # 0 0 0 K scn (grayscale CMYK via named CS)
                    for c, m, y, k in scn_hits:
                        if c != 0 or m != 0 or y != 0: continue
                        if k <= 0 or k >= 1.0: continue
                        k_pct = round(k * 100)
                        label = f"K:{k_pct}% (Black {k_pct}%)"
                        if label not in cmyk_found:
                            hex_val, rgb_val = self._cmyk_to_hex(0, 0, 0, k)
                            cmyk_found[label] = {'label': label, 'hex': hex_val,
                                                'rgb': rgb_val, 'space': 'CMYK', 'opacity': 100}

                    # Full CMYK via scn: c m y k scn
                    for c, m, y, k in scn_hits:
                        if self._skip_stream_color(c, m, y, k, painted): continue
                        if c == 0 and m == 0 and y == 0:
                            k_pct = round(k * 100)
                            label = f"K:{k_pct}% (Black {k_pct}%)"
                        else:
                            label = self._format_cmyk(c, m, y, k)
                        if label not in cmyk_found:
                            hex_val, rgb_val = self._cmyk_to_hex(c, m, y, k)
                            cmyk_found[label] = {'label': label, 'hex': hex_val,
                                                'rgb': rgb_val, 'space': 'CMYK', 'opacity': 100}

                    # Standard k operator fallback
                    for c, m, y, k in self._cmyk_operands(stream_text, 'k'):
                        if self._skip_stream_color(c, m, y, k, painted): continue
                        if c == 0 and m == 0 and y == 0:
                            k_pct = round(k * 100)
                            label = f"K:{k_pct}% (Black {k_pct}%)"
                        else:
                            label = self._format_cmyk(c, m, y, k)
                        if label not in cmyk_found:
                            hex_val, rgb_val = self._cmyk_to_hex(c, m, y, k)
                            cmyk_found[label] = {'label': label, 'hex': hex_val,
                                                'rgb': rgb_val, 'space': 'CMYK', 'opacity': 100}

                    # Grayscale g operator
                    gray_hits = re.findall(r'([0-9.]+) g ', stream_text)
                    for g_str in gray_hits:
                        g = float(g_str)
                        if g >= 1.0: continue
                        k_pct = round((1 - g) * 100)
                        label = f"K:{k_pct}% (Black {k_pct}%)"
                        if label not in cmyk_found:
                            hex_val, rgb_val = self._cmyk_to_hex(0, 0, 0, 1-g)
                            cmyk_found[label] = {'label': label, 'hex': hex_val,
                                                'rgb': rgb_val, 'space': 'CMYK', 'opacity': 100}

                    if cmyk_found:
                        fills = cmyk_found  # Replace RGB approximations with real CMYK
                except:
                    pass

            # Suppress RGB fills when we have better color data:
            # - If spot colors found: RGB are fitz approximations, useless
            # - If doc is CMYK: RGB are fitz conversions, misleading
            # RGB fills only shown if doc is genuinely RGB with no spot/CMYK data
            # Override color mode if content stream analysis found CMYK data
            # DeviceRGB can appear in PDF xrefs from rendering artifacts — trust fill data more
            has_cmyk_fills = any(v.get('space') == 'CMYK' for v in fills.values())
            if has_cmyk_fills and not spot_colors:
                results['color_mode'] = 'CMYK'
            elif spot_colors and has_cmyk_fills:
                results['color_mode'] = 'Spot + CMYK'
            elif spot_colors:
                results['color_mode'] = 'Spot Color'

            color_mode = results.get('color_mode', 'Unknown')
            suppress_rgb = spot_colors or ('CMYK' in color_mode and 'RGB' not in color_mode) or has_cmyk_fills
            if suppress_rgb:
                fills = {k: v for k, v in fills.items() if v.get('space') != 'RGB'}
                strokes = {k: v for k, v in strokes.items() if v.get('space') != 'RGB'}

            # Gradients and shading show up as hundreds of one-off colors: list a
            # dozen, say how many there are, and skip the "N colors = N screens" warning
            many_fills = len(fills) if len(fills) > 24 else 0
            if many_fills:
                fills = dict(list(fills.items())[:12])

            results['fills'] = list(fills.values())
            results['strokes'] = list(strokes.values())
            results['spot_colors'] = list(spot_colors.values())
            results['gradients'] = gradients
            if many_fills:
                results['warnings'].append(
                    f"🎨 {many_fills} different fill colors found (gradients or shading): this is full-color "
                    "artwork. The first 12 are listed.")

            # Generate warnings
            if gradients:
                results['warnings'].append("⚠️ Gradient detected — prints as halftone dots in screen print and can't be embroidered as a smooth blend")
            
            hairlines = [s for s in results['strokes'] if s.get('width', 1) < 0.5]
            if hairlines:
                results['warnings'].append("⚠️ Hairline stroke detected — may not reproduce in embroidery or laser engraving")

            total_colors = len(results['fills']) + len(results['spot_colors'])
            if total_colors > 6 and not many_fills:
                results['warnings'].append(f"⚠️ {total_colors} colors detected — in screen printing each color is a separate screen, so cost rises with every color")

            # Detect mixed color spaces
            spaces = set(f.get('space') for f in results['fills'])
            if len(spaces) > 1:
                results['warnings'].append("⚠️ Mixed color spaces detected — verify consistency before production")

            return results

        except Exception as e:
            results['warnings'].append(f"Color extraction error: {str(e)}")
            return results

    def _cmyk_operands(self, stream, op):
        """Every 'c m y k <op>' in a content stream as (c, m, y, k) floats, in order.

        Finds the operator first and then reads the four numbers in front of it.
        A single regex for "four numbers then the operator" took over a second per
        operator on a 5 MB stream, because almost everything in a stream is a number.
        """
        import re
        four_numbers = re.compile(r'([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+$')
        found = []
        for hit in re.finditer(r'(?<=\s)' + re.escape(op) + r'(?![A-Za-z0-9*])', stream):
            numbers = four_numbers.search(stream[max(0, hit.start() - 120):hit.start()])
            if not numbers:
                continue
            try:
                found.append(tuple(float(x) for x in numbers.groups()))
            except ValueError:
                continue
        return found

    def _painted_fill_colors(self, stream_text):
        """CMYK fill colors that are actually used to paint something on the page.

        Walks the content stream in order, tracking the current fill color and the
        q/Q graphics-state stack, and records the color each time a fill or
        text-showing operator runs. A color that is only *set* (for example an
        application's default black at the top of the stream) is not recorded.
        Returns a set of (c, m, y, k) tuples rounded to 3 places, or None if the
        stream could not be walked.
        """
        try:
            import re
            text = re.sub(r'\bBI\b.*?\bEI\b', ' ', stream_text, flags=re.DOTALL)   # inline images
            text = re.sub(r'\((?:\\.|[^\\()])*\)', ' ', text)                    # (string) literals
            text = re.sub(r'<[0-9A-Fa-f\s]*>', ' ', text)                          # <hex> strings
            tokens = re.findall(r"/[^\s/\[\]()<>{}%]*|[-+]?(?:\d+\.?\d*|\.\d+)|[A-Za-z'\"]+\*?|[\[\]]", text)

            painted = set()
            fill = None
            stack = []
            nums = []
            for tok in tokens:
                first = tok[0]
                if first.isdigit() or first in '+-.':
                    try:
                        nums.append(float(tok))
                    except ValueError:
                        pass
                    continue
                if first in '/[]':
                    continue
                # operator
                if tok == 'k' and len(nums) >= 4:
                    fill = tuple(round(v, 3) for v in nums[-4:])
                elif tok in ('scn', 'sc') and len(nums) == 4:
                    fill = tuple(round(v, 3) for v in nums[-4:])
                elif tok in ('scn', 'sc', 'rg', 'cs'):
                    fill = None            # not a 4-value CMYK color
                elif tok == 'g' and nums:
                    fill = (0.0, 0.0, 0.0, round(1 - nums[-1], 3))
                elif tok == 'q':
                    stack.append(fill)
                elif tok == 'Q':
                    fill = stack.pop() if stack else fill
                elif tok in ('f', 'F', 'f*', 'B', 'B*', 'b', 'b*', 'Tj', 'TJ', "'", '"'):
                    if fill is not None:
                        painted.add(fill)
                nums = []
            return painted
        except Exception:
            return None

    def _skip_stream_color(self, c, m, y, k, painted):
        """True for stream colors that should not be listed.

        Registration black (all four inks at 100%) and paper white are never
        listed. A pure 100% ink (C, M, Y or K alone) is listed only when it is
        really painted on the page; `painted` comes from _painted_fill_colors().
        If the stream could not be walked (painted is None) pure inks are
        skipped, which is how every pure ink was treated before.
        """
        vals = (round(c, 1), round(m, 1), round(y, 1), round(k, 1))
        if vals in ((1, 1, 1, 1), (0, 0, 0, 0)):
            return True
        if vals in ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)):
            if painted is None:
                return True
            return (round(c, 3), round(m, 3), round(y, 3), round(k, 3)) not in painted
        return False

    def _extract_from_eps(self, input_file, results):
        """Extract colors from EPS using GS->PDF->fitz pipeline for binary EPS support"""
        import re

        results['color_mode'] = self._detect_color_mode_eps(input_file)
        tmp_pdf = None
        try:
            eps_pdf_bytes = convert_eps_to_pdf(input_file)   # shared with font check + PDF download
            if eps_pdf_bytes:
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                    tmp.write(eps_pdf_bytes)
                    tmp_pdf = tmp.name

            if eps_pdf_bytes and os.path.exists(tmp_pdf):
                import fitz
                doc = fitz.open(tmp_pdf)
                page = doc[0]
                stream = page.read_contents().decode('latin-1', errors='ignore')
                doc.close()

                fills = {}
                spot_colors = {}
                painted = self._painted_fill_colors(stream)

                # Spot colors from original EPS text
                try:
                    with open(input_file, 'r', errors='ignore') as f:
                        eps_text = f.read()
                    import string
                    declared = self._eps_dsc_colors(eps_text)['custom']
                    if declared is not None:
                        # The file states its spot colors (Pantone or custom-named): use exactly those
                        for sp in declared:
                            if all(c in string.printable for c in sp):
                                spot_colors[sp] = {'label': sp, 'type': 'spot'}
                    else:
                        for sp in re.findall(r'\(([^)]*(?:PANTONE|Pantone|PMS)[^)]*)\)', eps_text):
                            sp = sp.strip()
                            # Skip garbage binary matches - valid Pantone names are printable ASCII
                            if sp and len(sp) < 50 and all(c in string.printable for c in sp):
                                spot_colors[sp] = {'label': sp, 'type': 'spot'}
                except: pass

                has_spots = bool(spot_colors)

                # Parse CMYK from decompressed stream (k and scn operators)
                if not has_spots:
                    for op in ('k', 'scn'):
                        for c, m, y, k in self._cmyk_operands(stream, op):
                            if self._skip_stream_color(c, m, y, k, painted): continue
                            if c == 0 and m == 0 and y == 0:
                                k_pct = round(k * 100)
                                if k_pct == 0: continue
                                label = f"K:{k_pct}% (Black {k_pct}%)"
                            else:
                                label = self._format_cmyk(c, m, y, k)
                            if label not in fills:
                                hex_val, rgb_val = self._cmyk_to_hex(c, m, y, k)
                                fills[label] = {'label': label, 'hex': hex_val,
                                               'rgb': rgb_val, 'space': 'CMYK', 'opacity': 100}

                # RGB artwork: Ghostscript keeps the file's own color space, so an RGB
                # EPS arrives as 'r g b rg' fills. Without this an RGB file listed no
                # colors at all and was labelled CMYK (the word is in Illustrator's
                # boilerplate). Paper white is left out, as it is for CMYK.
                rgb_total = 0
                if not fills and not has_spots:
                    rgb_uses = {}
                    for r_s, g_s, b_s in re.findall(
                            r'(?<![\d.])([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+rg(?![A-Za-z0-9*])', stream):
                        try:
                            r, g, b = float(r_s), float(g_s), float(b_s)
                        except ValueError:
                            continue
                        if max(r, g, b) > 1 or (r >= 0.995 and g >= 0.995 and b >= 0.995):
                            continue
                        key = (round(r * 255), round(g * 255), round(b * 255))
                        rgb_uses[key] = rgb_uses.get(key, 0) + 1
                    rgb_total = len(rgb_uses)
                    # Gradients and shading arrive as hundreds of one-off colors:
                    # list the most used ones instead of all of them
                    listed = sorted(rgb_uses, key=lambda c: -rgb_uses[c])[:12] if rgb_total > 24 else list(rgb_uses)
                    for r8, g8, b8 in listed:
                        label = f"R:{r8} G:{g8} B:{b8}"
                        hex_val, rgb_val = self._rgb_to_hex(r8 / 255, g8 / 255, b8 / 255)
                        fills[label] = {'label': label, 'hex': hex_val, 'rgb': rgb_val,
                                        'space': 'RGB', 'opacity': 100}
                    if fills:
                        results['color_mode'] = 'RGB'
                    if rgb_total > 24:
                        results['warnings'].append(
                            f"🎨 {rgb_total} different RGB colors found (gradients or shading): this is full-color "
                            "artwork. The 12 most used colors are listed.")

                results['fills'] = list(fills.values())
                results['strokes'] = []
                results['spot_colors'] = list(spot_colors.values())

                if not fills and not spot_colors:
                    results['warnings'].append("Could not extract color data from this EPS file.")
                total = len(fills) + len(spot_colors)
                if total > 6 and rgb_total <= 24:
                    results['warnings'].append(f"⚠️ {total} colors detected — in screen printing each color is a separate screen, so cost rises with every color")
                return results

        except Exception as e:
            results['warnings'].append(f"EPS color extraction error: {str(e)}")
        finally:
            if tmp_pdf and os.path.exists(tmp_pdf):
                os.unlink(tmp_pdf)

        return results

    def _detect_color_mode_pdf(self, input_file):
        """Detect document color mode from PDF/AI xref objects + full raw byte scan"""
        has_cmyk = False
        has_rgb = False
        has_spot = False
        try:
            import fitz
            doc = fitz.open(input_file)
            # (this used to call doc.xref_count(), which does not exist: the error was
            # swallowed and only the raw scan below ran, which cannot see inside
            # compressed objects, so such files came out as "Unknown")
            for xref in range(1, min(doc.xref_length(), 5000)):
                try:
                    obj = doc.xref_object(xref)
                    if '/DeviceCMYK' in obj: has_cmyk = True
                    if '/DeviceRGB' in obj: has_rgb = True
                    if '/Separation' in obj or 'PANTONE' in obj: has_spot = True
                except: pass
            # What the page itself paints with. (Not get_drawings(): it reports every
            # fill as RGB, whatever the file uses.)
            try:
                import re
                ops = doc[0].read_contents().decode('latin-1', errors='ignore')
                if re.search(r'(?<=\s)(k|K)(?=\s)', ops): has_cmyk = True
                if re.search(r'(?<=\s)(rg|RG)(?=\s)', ops): has_rgb = True
            except: pass
            doc.close()
        except: pass
        try:
            # Full file raw scan — read entire file for keyword detection
            with open(input_file, 'rb') as f:
                raw = f.read().decode('latin-1', errors='ignore')
            if 'PANTONE' in raw or '/Separation' in raw: has_spot = True
            if 'DeviceCMYK' in raw or 'setcmykcolor' in raw: has_cmyk = True
            if 'DeviceRGB' in raw or 'setrgbcolor' in raw: has_rgb = True
        except: pass
        if has_spot and has_cmyk: return 'Spot + CMYK'
        if has_spot: return 'Spot Color'
        if has_cmyk and has_rgb: return 'Mixed (CMYK + RGB)'
        if has_cmyk: return 'CMYK'
        if has_rgb: return 'RGB'
        return 'Unknown'

    def _eps_dsc_colors(self, text):
        """Inks an EPS declares in its header comments (DSC).

        %%DocumentCustomColors lists spot colors by name, one "(Name)" each, and
        %%DocumentProcessColors lists the process inks (Cyan Magenta Yellow Black).
        Both may continue on "%%+" lines. Returns {'custom': [...], 'process': [...]}
        with None for a comment that is absent (or only says "(atend)").
        """
        import re
        out = {'custom': None, 'process': None}
        lines = text.splitlines()
        for i, line in enumerate(lines):
            for key, field in (('%%DocumentCustomColors:', 'custom'), ('%%DocumentProcessColors:', 'process')):
                if not line.startswith(key):
                    continue
                value = line[len(key):]
                j = i + 1
                while j < len(lines) and lines[j].startswith('%%+'):
                    value += ' ' + lines[j][3:]
                    j += 1
                if '(atend)' in value:
                    continue
                if field == 'custom':
                    names = [n.replace('\\(', '(').replace('\\)', ')').strip()
                             for n in re.findall(r'\(((?:\\.|[^()\\])*)\)', value)]
                    out['custom'] = [n for n in names if n and len(n) < 60]
                else:
                    out['process'] = [w for w in value.split() if w in ('Cyan', 'Magenta', 'Yellow', 'Black')]
        return out

    def _detect_color_mode_eps(self, input_file):
        """Detect document color mode from EPS file"""
        has_spot = False
        has_cmyk = False
        has_rgb = False
        try:
            import re
            with open(input_file, 'r', errors='ignore') as f:
                full = f.read()
            # Illustrator (and any DSC-conforming EPS) declares its inks in the header.
            # Trust that when present. The bare word "Separation" is NOT evidence of a
            # spot color: it is in the boilerplate of every Illustrator EPS.
            dsc = self._eps_dsc_colors(full)
            if dsc['custom'] is not None:
                has_spot = len(dsc['custom']) > 0
            elif re.search(r'PANTONE', full):
                has_spot = True
            if dsc['process'] is not None:
                has_cmyk = len(dsc['process']) > 0
            elif re.search(r'setcmykcolor|DeviceCMYK|CMYKCustomColor', full):
                has_cmyk = True
            if re.search(r'setrgbcolor|DeviceRGB', full): has_rgb = True
        except: pass
        if has_spot and has_cmyk: return 'Spot + CMYK'
        if has_spot: return 'Spot Color'
        if has_cmyk: return 'CMYK'
        if has_rgb: return 'RGB'
        return 'Unknown'

    def _detect_color_mode_svg(self, content):
        """Detect color mode from SVG content"""
        import re
        has_pantone = bool(re.search(r'pantone|PANTONE', content, re.IGNORECASE))
        has_icc_cmyk = 'icc-color' in content and 'cmyk' in content.lower()
        has_hex = bool(re.search(r'#[0-9a-fA-F]{3,6}', content))
        if has_pantone: return 'Spot Color'
        if has_icc_cmyk: return 'CMYK'
        if has_hex: return 'RGB'
        return 'Unknown'

    def _extract_from_svg(self, input_file, results):
        """Extract colors from SVG by parsing XML"""
        try:
            import re
            with open(input_file, 'r', errors='ignore') as f:
                content = f.read()

            fills = {}
            strokes = {}
            spot_colors = {}

            results['color_mode'] = self._detect_color_mode_svg(content)

            # Spot colors — Pantone names in id attributes or content
            pantone_hits = re.findall(r'(?:PANTONE|Pantone)[^\s<>/]{1,40}', content)
            for ph in pantone_hits:
                ph = ph.strip().strip("\"-'")
                if ph:
                    spot_colors[ph] = {'label': ph, 'type': 'spot'}

            fill_matches = re.findall(r'fill[\s:="\']+([#][0-9a-fA-F]{3,6})', content)
            stroke_matches = re.findall(r'stroke[\s:="\']+([#][0-9a-fA-F]{3,6})', content)
            stroke_widths = re.findall(r'stroke-width[\s:="\']+([\d.]+)', content)

            has_spots = len(spot_colors) > 0
            artifact_hex = {'#ffffff', '#000000', '#fff', '#000'}

            for val in fill_matches:
                if has_spots and val.lower() in artifact_hex:
                    continue
                fills[val] = {'label': val.upper(), 'hex': val, 'space': 'RGB', 'opacity': 100}

            avg_width = sum(float(w) for w in stroke_widths) / len(stroke_widths) if stroke_widths else 1.0
            for val in stroke_matches:
                if has_spots and val.lower() in artifact_hex:
                    continue
                strokes[val] = {'label': val.upper(), 'hex': val, 'space': 'RGB',
                               'width': avg_width, 'opacity': 100}

            results['fills'] = list(fills.values())
            results['strokes'] = list(strokes.values())
            results['spot_colors'] = list(spot_colors.values())

            if not results['fills'] and not results['spot_colors']:
                results['warnings'].append("Could not extract color data from this SVG.")

            total = len(results['fills']) + len(results['spot_colors'])
            if total > 6:
                results['warnings'].append(f"⚠️ {total} colors detected — in screen printing each color is a separate screen, so cost rises with every color")

            return results
        except Exception as e:
            results['warnings'].append(f"SVG color extraction error: {str(e)}")
            return results



class FontChecker:
    """Finds live (non-outlined) text in vector files.

    check() returns None when the file could not be inspected, otherwise:
      {'live_text': bool,
       'fonts': [{'name': str, 'embedded': True | False | None}],   # None = not known
       'sample': str}                                               # a few words of the text
    Only page 1 is inspected, matching the preview and color analysis.
    """

    MAX_FONTS = 8

    def check(self, input_file):
        ext = Path(input_file).suffix.lower()
        try:
            if ext in ('.pdf', '.ai'):
                return self._check_pdf(input_file)
            if ext == '.eps':
                return self._check_eps(input_file)
            if ext == '.svg':
                return self._check_svg(input_file)
        except Exception:
            return None
        return None

    @staticmethod
    def _clean_font_name(name):
        """Drop the 6-letter subset prefix PDFs add, e.g. 'ABCDEF+Helvetica-Bold'."""
        import re
        return re.sub(r'^[A-Z]{6}\+', '', (name or '').strip())

    def _check_pdf(self, input_file):
        import fitz
        doc = fitz.open(input_file)
        try:
            page = doc[0]
            # Which fonts are embedded in the file (ext 'n/a' = not embedded)
            embedded = {}
            for font in page.get_fonts(full=True):
                embedded[self._clean_font_name(font[3])] = (font[1] != 'n/a')

            names, words = [], []
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = (span.get("text") or "").strip()
                        if not text:
                            continue
                        name = self._clean_font_name(span.get("font"))
                        if name and name not in names:
                            names.append(name)
                        if len(" ".join(words)) < 60:
                            words.append(text)
        finally:
            doc.close()

        fonts = [{'name': n, 'embedded': embedded.get(n)} for n in names[:self.MAX_FONTS]]
        return {'live_text': bool(names or words), 'fonts': fonts, 'sample': " ".join(words)[:60]}

    def _eps_declared_fonts(self, input_file):
        """Font names an EPS says it uses (header comments and findfont calls)."""
        import re
        try:
            with open(input_file, 'rb') as f:
                text = f.read(2_000_000).decode('latin-1', errors='ignore')
        except Exception:
            return []
        names = []
        for m in re.finditer(r'%%DocumentFonts:[ \t]*([^\r\n]*)', text):
            names += [t for t in m.group(1).split() if t != '(atend)']
        names += re.findall(r'%%IncludeResource:[ \t]*font[ \t]+(\S+)', text)
        names += re.findall(r'/([A-Za-z][A-Za-z0-9_\-]{1,60})\s+(?:findfont|selectfont)\b', text)
        seen = []
        for n in names:
            if n not in seen:
                seen.append(n)
        return seen[:self.MAX_FONTS]

    def _check_eps(self, input_file):
        """EPS -> PDF with Ghostscript, then look for text the same way as a PDF."""
        tmp_pdf = None
        try:
            eps_pdf_bytes = convert_eps_to_pdf(input_file)   # shared with color analysis + PDF download
            if not eps_pdf_bytes:
                return None
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(eps_pdf_bytes)
                tmp_pdf = tmp.name
            result = self._check_pdf(tmp_pdf)
        finally:
            if tmp_pdf and os.path.exists(tmp_pdf):
                try:
                    os.unlink(tmp_pdf)
                except Exception:
                    pass
        if result and result['live_text']:
            # Ghostscript may swap in its own look-alike fonts, so prefer the
            # names the EPS itself declares. Embedding is not known for EPS.
            declared = self._eps_declared_fonts(input_file)
            names = declared or [f['name'] for f in result['fonts']]
            result['fonts'] = [{'name': n, 'embedded': None} for n in names]
        return result

    def _check_svg(self, input_file):
        import re
        with open(input_file, 'r', errors='ignore') as f:
            content = f.read(5_000_000)
        if not re.search(r'<text[\s>]', content, re.IGNORECASE):
            return {'live_text': False, 'fonts': [], 'sample': ''}
        names = []
        for m in re.finditer(r'font-family\s*[:=]\s*["\']?\s*([^;"\'<>]+)', content, re.IGNORECASE):
            first = m.group(1).split(',')[0].strip().strip('"\'').replace('&quot;', '').strip()
            if first and first not in names:
                names.append(first)
        sample = " ".join(re.sub(r'<[^>]+>', ' ', " ".join(
            re.findall(r'<text[\s>].*?</text>', content, re.IGNORECASE | re.DOTALL)[:3])).split())[:60]
        return {'live_text': True, 'fonts': [{'name': n, 'embedded': None} for n in names[:self.MAX_FONTS]],
                'sample': sample}


class PdfConverter:
    """Converts EPS, AI and SVG files to PDF WITHOUT rasterizing.

    The art must never pass through an image on the way: building a PDF from
    the preview PNG puts a picture inside a PDF wrapper. Each format is
    converted from its drawing instructions instead:
      EPS -> Ghostscript pdfwrite (keeps paths, CMYK values and spot colors)
      AI  -> the PDF copy Illustrator stores inside the file, re-saved with fitz
      SVG -> CairoSVG's PDF surface
      CDR -> convert_cdr(): libcdr -> clean SVG -> PDF (page 1, RGB)
    Every result is inspected afterwards, so the UI can say whether the PDF
    really is vector instead of assuming it.

    convert() returns (pdf_bytes or None, info) where info is
      {'ok', 'source', 'pages', 'paths', 'images', 'has_text', 'vector', 'error'}
    """

    SOURCE_FORMATS = ('.eps', '.ai', '.svg', '.cdr')

    def can_convert(self, filename):
        return Path(filename).suffix.lower() in self.SOURCE_FORMATS

    def convert(self, input_file):
        ext = Path(input_file).suffix.lower()
        info = {'ok': False, 'source': ext, 'pages': 0, 'paths': 0, 'images': 0,
                'has_text': False, 'vector': False, 'error': None}
        out_pdf = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                out_pdf = tmp.name
            if ext == '.eps':
                made = self._eps_to_pdf(input_file, out_pdf)
            elif ext == '.ai':
                made = self._ai_to_pdf(input_file, out_pdf, info)
            elif ext == '.svg':
                made = self._svg_to_pdf(input_file, out_pdf)
            elif ext == '.cdr':
                made = self._cdr_to_pdf(input_file, out_pdf, info)
            else:
                made = False
            if not made or not os.path.exists(out_pdf) or os.path.getsize(out_pdf) == 0:
                info['error'] = info['error'] or "This file could not be converted to PDF."
                return None, info
            self._inspect(out_pdf, info)
            if info['pages'] == 0:
                info['error'] = "The converted PDF has no pages."
                return None, info
            with open(out_pdf, 'rb') as f:
                pdf_bytes = f.read()
            info['ok'] = True
            return pdf_bytes, info
        except Exception as e:
            info['error'] = f"PDF conversion failed: {e}"
            return None, info
        finally:
            if out_pdf and os.path.exists(out_pdf):
                try:
                    os.unlink(out_pdf)
                except Exception:
                    pass

    def _eps_to_pdf(self, input_file, out_pdf):
        eps_pdf_bytes = convert_eps_to_pdf(input_file)   # shared with color analysis + font check
        if not eps_pdf_bytes:
            return False
        with open(out_pdf, 'wb') as f:
            f.write(eps_pdf_bytes)
        return True

    def _ai_to_pdf(self, input_file, out_pdf, info):
        import fitz
        doc = fitz.open(input_file)
        try:
            if not doc.is_pdf or doc.page_count == 0:
                info['error'] = "This .ai file has no PDF content inside, so it can't be converted here."
                return False
            if 'saved without PDF Content' in doc[0].get_text():
                info['error'] = ("This .ai file was saved without PDF compatibility. Ask for it to be re-saved from "
                                 "Illustrator with “Create PDF Compatible File” checked.")
                return False
            doc.save(out_pdf, garbage=3, deflate=True)
            return True
        finally:
            doc.close()

    def _cdr_to_pdf(self, input_file, out_pdf, info):
        converted = convert_cdr(input_file)
        if not converted:
            info['error'] = ("This CorelDRAW file could not be converted. Ask for a PDF exported from CorelDRAW instead.")
            return False
        with open(out_pdf, 'wb') as f:
            f.write(converted['pdf'])
        return True

    def _svg_to_pdf(self, input_file, out_pdf):
        import cairosvg
        with open(input_file, 'rb') as f:
            cairosvg.svg2pdf(bytestring=f.read(), write_to=out_pdf)
        return True

    def _inspect(self, pdf_path, info):
        """Count vector paths, raster images and text in the converted PDF (first 5 pages)."""
        import fitz
        doc = fitz.open(pdf_path)
        try:
            info['pages'] = doc.page_count
            for page in list(doc)[:5]:
                info['paths'] += len(page.get_cdrawings())   # same list as get_drawings(), half the time
                info['images'] += len(page.get_images())
                if page.get_text().strip():
                    info['has_text'] = True
        finally:
            doc.close()
        info['vector'] = info['images'] == 0 and (info['paths'] > 0 or info['has_text'])


def render_pdf_export(pdf_bytes, info, filename_stem, live_text=False):
    """Download button for the vector PDF, with what was verified about it."""
    if not info:
        return
    if not info.get('ok') or not pdf_bytes:
        st.caption(f"📄 PDF version not available: {info.get('error') or 'conversion failed'}")
        return
    st.download_button(
        label="⬇️ Download PDF (vector)" if info.get('vector') else "⬇️ Download PDF",
        data=pdf_bytes,
        file_name=f"{filename_stem}.pdf",
        mime="application/pdf",
        use_container_width=True,
        key="download_pdf_button",
    )
    if info.get('vector'):
        st.caption("✅ **Vector preserved** — converted straight from the original artwork, with no raster images in the PDF.")
    elif info.get('images') and not info.get('paths') and not info.get('has_text'):
        st.caption("⚠️ **Not vector.** The original file is a picture saved inside a vector file, so the PDF is a picture too.")
    elif info.get('images'):
        st.caption(f"⚠️ **Partly raster.** The PDF contains {info['images']} raster image(s) that were already in the original file. "
                   "The rest of the art is vector.")
    else:
        st.caption("⚠️ ArtCheck could not confirm vector content in this PDF. Check it before sending.")
    notes = []
    if (info.get('pages') or 1) > 1:
        notes.append(f"The PDF contains all {info['pages']} pages of the file, not only the page shown above.")
    if live_text:
        notes.append("This file has live text. Where a font isn't inside the file, the PDF shows a substitute typeface — compare it with the original before sending.")
    if info.get('source') == '.svg':
        notes.append("SVG colors are RGB, so this PDF is RGB too.")
    elif info.get('source') == '.cdr':
        notes.append("Converted from CorelDRAW: colors come out as RGB (Pantone and CMYK values are not carried over) "
                     "and gradients become fine solid bands. For production, ask for a PDF exported from CorelDRAW itself.")
    elif info.get('source') in ('.eps', '.ai'):
        notes.append("CMYK values and Pantone spot colors are carried over from the original.")
    for note in notes:
        st.caption(note)


def render_font_check(font_check):
    """Show whether the file still contains live text (fonts not outlined)."""
    if not font_check:
        return
    import html as _html
    st.markdown("---")
    st.markdown("### 🔤 Font Check")
    if not font_check.get('live_text'):
        st.markdown('<div style="padding:12px;border-radius:8px;background:#1a6b3a;color:#fff;font-size:1rem;'
                    'font-weight:bold;margin-bottom:12px;">✅ No live text found — fonts are outlined (or the file has no text)</div>',
                    unsafe_allow_html=True)
        return

    st.markdown('<div style="padding:12px;border-radius:8px;background:#8b1a1a;color:#fff;font-size:1rem;'
                'font-weight:bold;margin-bottom:12px;">⚠️ Live text found — fonts are NOT outlined</div>',
                unsafe_allow_html=True)
    fonts = font_check.get('fonts') or []
    if fonts:
        parts = []
        for f in fonts:
            note = ' (not embedded)' if f.get('embedded') is False else (' (embedded)' if f.get('embedded') else '')
            parts.append(f"<code>{_html.escape(f['name'])}</code>{note}")
        st.markdown("**Fonts used:** " + ", ".join(parts), unsafe_allow_html=True)
    if font_check.get('sample'):
        st.markdown(f"**Text found:** <code>{_html.escape(font_check['sample'])}</code>", unsafe_allow_html=True)
    if any(f.get('embedded') is False for f in fonts):
        st.caption("Fonts marked “not embedded” are not inside the file at all — the preview above may already be showing a substitute typeface.")
    st.warning("""
**This file contains editable text that has not been converted to outlines.**

If the art department doesn't have the exact same fonts installed, the text can change to a different typeface, shift, or reflow when the file is opened.

**What to tell your customer:**
> "Your file contains live text that hasn't been converted to outlines. To make sure your text prints exactly as you designed it, please convert all text to outlines (in Illustrator: Select All, then Type → Create Outlines) and resend the file."
    """)


def render_decoration_check(facts, file_label=""):
    """Decoration Method Check: pick a method (and location) and screen the file for it."""
    try:
        _render_decoration_check(facts, file_label)
    except Exception as err:
        st.caption(f"Decoration Method Check is unavailable for this file ({err}).")


def _render_decoration_check(facts, file_label):
    dr = decoration_rules
    st.markdown("---")
    st.markdown("### 🎯 Decoration Method Check")
    st.caption("Choose how this art will be decorated to see whether the file is a good fit.")

    ctx = st.session_state.get('artbot_file_context')
    col_method, col_location, col_width = st.columns([3, 3, 2])
    with col_method:
        method = st.selectbox(
            "Decoration method", [""] + dr.method_keys(),
            format_func=lambda k: dr.method_label(k) if k else "— Select a method —",
            key="prescreen_method",
        )
    if not method:
        if isinstance(ctx, dict):
            ctx.pop('prescreen', None)
        return

    location = ""
    if dr.location_keys(method):
        with col_location:
            location = st.selectbox(
                "Imprint location", [""] + dr.location_keys(method),
                format_func=lambda k: dr.location_label(k) if k else "— Not specified —",
                key="prescreen_location",
            )
    location = location or None

    print_width = None
    if dr.asks_for_print_width(facts, method, location):
        max_w = float(dr.max_print_width(facts, method, location))
        with col_width:
            print_width = st.number_input(
                "Print width (in)", min_value=min(0.25, max_w), max_value=max_w, value=max_w, step=0.25,
                key=f"prescreen_width_{method}_{location}_{file_label}",
                help="Starts at the largest size that fits. Lower it to the size you actually plan to print.",
            )

    ev = dr.evaluate(facts, method, location, print_width)
    label = dr.method_label(method)
    banner = {
        'pass': ('#1a6b3a', f'✅ No problems found for {label}'),
        'warn': ('#7d5a00', f'⚠️ Needs attention for {label}'),
        'fail': ('#8b1a1a', f'❌ Not suitable as-is for {label}'),
    }[ev['verdict']]
    st.markdown(
        f'<div style="padding:12px;border-radius:8px;background:{banner[0]};color:#fff;font-size:1rem;'
        f'font-weight:bold;margin-bottom:12px;">{banner[1]}</div>', unsafe_allow_html=True)

    if ev['fails']:
        st.markdown("**Problems:**\n" + "\n".join(f"- ❌ {t}" for t in ev['fails']))
    if ev['warns']:
        st.markdown("**Warnings:**\n" + "\n".join(f"- ⚠️ {t}" for t in ev['warns']))
    if ev['notes']:
        st.markdown("**Good to know:**\n" + "\n".join(f"- {t}" for t in ev['notes']))
    if ev['confirm']:
        st.markdown("**Also confirm (ArtCheck can't see this from the file):**\n" + "\n".join(f"- {t}" for t in ev['confirm']))

    script = dr.customer_script(ev)
    if script:
        st.warning("**What to tell your customer:**\n\n> \"" + script.replace("\n", "\n> ").replace("> > ", "> ") + "\"")

    st.caption(f"📋 {dr.DISCLAIMER} Guidelines courtesy of [{dr.GUIDE_NAME}]({dr.GUIDE_URL}).")

    if isinstance(ctx, dict):
        ctx['prescreen'] = dr.artbot_summary(ev)


def _safe_hex(value):
    """A color for a style attribute: '#rgb' or '#rrggbb', anything else becomes gray."""
    import re
    value = str(value or '')
    return value if re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', value) else '#cccccc'


def render_color_results(color_data, file_ext):
    """Render color extraction results in Streamlit"""
    if not color_data:
        return

    st.markdown("---")
    st.markdown("### 🎨 Color Analysis")

    has_anything = (color_data.get('spot_colors') or color_data.get('fills') or
                   color_data.get('strokes') or color_data.get('gradients'))

    if not has_anything and not color_data.get('warnings'):
        st.info("No color data extracted from this file.")
        return

    # Document color mode badge
    color_mode = color_data.get('color_mode')
    if color_mode:
        is_warning = 'RGB' in color_mode and 'Spot' not in color_mode
        mode_color = '#c0392b' if is_warning else '#1a6b3a'
        mode_icon = '⚠️' if is_warning else '✅'
        badge = f'<div style="display:inline-block;padding:4px 12px;border-radius:12px;background:{mode_color};color:#fff;font-size:0.85rem;font-weight:bold;margin-bottom:8px;">{mode_icon} Document Color Mode: {color_mode}</div>'
        st.markdown(badge, unsafe_allow_html=True)
        if is_warning:
            st.warning("⚠️ RGB color mode detected — colors may shift significantly in print. CMYK or Spot Color recommended.")

    # Spot colors (Pantone)
    if color_data.get('spot_colors'):
        st.markdown("**🎯 Spot Colors (Pantone/Named):**")
        for sc in color_data['spot_colors']:
            label = sc['label']
            swatch = '<span style="display:inline-block;width:16px;height:16px;background:#888;border:1px solid #666;border-radius:3px;vertical-align:middle;margin-right:6px;"></span>'
            st.markdown(f"{swatch}<code>{html.escape(str(label))}</code>", unsafe_allow_html=True)

    # Fill colors
    if color_data.get('fills'):
        st.markdown("**🖌️ Fill Colors:**")
        for fill in color_data['fills']:
            hex_val = _safe_hex(fill.get('hex'))
            opacity = fill.get('opacity', 100)
            opacity_str = f" @ {opacity}% opacity" if opacity < 100 else ""
            swatch = f'<span style="display:inline-block;width:16px;height:16px;background:{hex_val};border:1px solid #666;border-radius:3px;vertical-align:middle;margin-right:6px;"></span>'
            st.markdown(
f'{swatch}<code>{html.escape(str(fill["label"]))}</code>{opacity_str} <span style="color:#888;font-size:0.85rem;">({html.escape(str(fill.get("space","")))})</span>',
                unsafe_allow_html=True
            )

    # Stroke colors
    if color_data.get('strokes'):
        st.markdown("**✏️ Stroke Colors:**")
        for stroke in color_data['strokes']:
            hex_val = _safe_hex(stroke.get('hex'))
            width = stroke.get('width', 1)
            hairline = " ⚠️ hairline" if width < 0.5 else ""
            swatch = f'<span style="display:inline-block;width:16px;height:16px;background:{hex_val};border:1px solid #666;border-radius:3px;vertical-align:middle;margin-right:6px;"></span>'
            st.markdown(
                f'{swatch}<code>{html.escape(str(stroke["label"]))}</code> — {width}pt{hairline}',
                unsafe_allow_html=True
            )

    # Gradients
    if color_data.get('gradients'):
        st.markdown("**🌈 Gradients:**")
        st.markdown(f"• {len(color_data['gradients'])} gradient(s) detected")

    # Warnings
    if color_data.get('warnings'):
        st.markdown("**⚠️ Production Warnings:**")
        for w in color_data['warnings']:
            st.warning(w)


# ============================================================================
# SIDEBAR - ASK ARTBOT
# ============================================================================

def artbot_chat_page(history):
    """Self-contained HTML page for ArtBot's conversation box (shown in an iframe).

    ArtBot answers are Markdown. They used to be pasted into the page as raw
    HTML, so headings showed as literal '#', and any '<' typed by a user or
    produced by the model was treated as markup. Here the Markdown is converted
    to HTML with raw HTML disabled (escaped), and user text is escaped.
    """
    try:
        from markdown_it import MarkdownIt
        _md = MarkdownIt("commonmark", {"html": False}).enable("table")

        def render_answer(text):
            return _md.render(text or "").replace("<a href=", '<a target="_blank" rel="noopener noreferrer" href=')
    except Exception:
        def render_answer(text):
            return "<p>" + html.escape(text or "").replace("\n", "<br>") + "</p>"

    parts = []
    if not history:
        parts.append('<div class="empty">💬 Conversation will appear here<br><br>'
                     '<span>Use the input box below to ask a question</span></div>')
    for msg in history:
        if msg.get("role") == "user":
            parts.append('<div class="msg user">' + html.escape(msg.get("content") or "").replace("\n", "<br>") + '</div>')
        else:
            parts.append('<div class="msg bot"><div class="who">🤖 ArtBot</div>' + render_answer(msg.get("content")) + '</div>')

    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;}
html{color-scheme:dark;}
html[data-theme="light"]{color-scheme:light;}
html,body{margin:0;height:100%;background:transparent;}
body{font-family:"Source Sans Pro",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:15px;line-height:1.5;color:#e0e0e0;}
#box{height:100%;overflow-y:auto;padding:8px;border:2px solid #1e3a5f;border-radius:8px;background:#0d1117;
  scrollbar-width:thin;scrollbar-color:#3d5a80 #0d1117;}
/* Dark scrollbar: without this, browsers that always show scrollbars draw a white track */
#box::-webkit-scrollbar{width:10px;}
#box::-webkit-scrollbar-track{background:#0d1117;border-radius:8px;}
#box::-webkit-scrollbar-thumb{background:#3d5a80;border-radius:6px;border:2px solid #0d1117;}
.empty{color:#555;font-size:0.9rem;text-align:center;padding-top:40px;}
.empty span{color:#444;font-size:0.85rem;}
.msg{margin:4px 0;padding:6px 10px;overflow-wrap:anywhere;}
.user{background:#2b2d42;border-radius:10px 10px 3px 10px;color:#fff;text-align:right;}
.bot{background:#1e3a5f;border-radius:10px 10px 10px 3px;}
.who{font-size:0.8rem;color:#9fb8d8;margin-bottom:2px;}
.bot h1,.bot h2,.bot h3,.bot h4,.bot h5,.bot h6{font-size:1.02em;color:#fff;margin:10px 0 4px;}
.bot .who + *{margin-top:0;}
.bot p{margin:0 0 8px;}
.bot > :last-child{margin-bottom:0;}
.bot ul,.bot ol{margin:0 0 8px;padding-left:20px;}
.bot li{margin:2px 0;}
.bot blockquote{margin:6px 0 8px;padding:6px 10px;border-left:3px solid #8fa8ff;background:rgba(255,255,255,0.07);border-radius:4px;}
.bot blockquote p:last-child{margin-bottom:0;}
.bot hr{border:none;border-top:1px solid rgba(255,255,255,0.2);margin:10px 0;}
.bot code{background:rgba(0,0,0,0.3);padding:1px 4px;border-radius:3px;font-size:0.9em;}
.bot pre{background:rgba(0,0,0,0.3);padding:8px;border-radius:4px;overflow-x:auto;}
.bot pre code{background:none;padding:0;}
.bot table{border-collapse:collapse;margin:0 0 8px;font-size:0.92em;}
.bot th,.bot td{border:1px solid rgba(255,255,255,0.25);padding:3px 6px;text-align:left;}
.bot a{color:#9cc2ff;}
/* Light version (the sun / moon button sets data-theme through the script below) */
html[data-theme="light"] body{color:#1f2733;}
html[data-theme="light"] #box{border-color:#b9c8e2;background:#ffffff;scrollbar-color:#9fb3d6 #ffffff;}
html[data-theme="light"] #box::-webkit-scrollbar-track{background:#ffffff;}
html[data-theme="light"] #box::-webkit-scrollbar-thumb{background:#9fb3d6;border-color:#ffffff;}
html[data-theme="light"] .empty{color:#7a8291;}
html[data-theme="light"] .empty span{color:#959dab;}
html[data-theme="light"] .user{background:#dfe3ee;color:#1f2733;}
html[data-theme="light"] .bot{background:#e4edfb;}
html[data-theme="light"] .who{color:#4a6592;}
html[data-theme="light"] .bot h1,html[data-theme="light"] .bot h2,html[data-theme="light"] .bot h3,
html[data-theme="light"] .bot h4,html[data-theme="light"] .bot h5,html[data-theme="light"] .bot h6{color:#16233a;}
html[data-theme="light"] .bot blockquote{border-left-color:#5b76d6;background:rgba(40,70,140,0.08);}
html[data-theme="light"] .bot hr{border-top-color:rgba(20,40,80,0.2);}
html[data-theme="light"] .bot code,html[data-theme="light"] .bot pre{background:rgba(20,40,80,0.09);}
html[data-theme="light"] .bot th,html[data-theme="light"] .bot td{border-color:rgba(20,40,80,0.25);}
html[data-theme="light"] .bot a{color:#1f56b3;}
</style></head><body>
<div id="box">""" + "".join(parts) + """</div>
<script>
// Show the newest question at the top of the box so its answer can be read from the start
var box=document.getElementById('box'), asked=document.querySelectorAll('.user');
if(asked.length){box.scrollTop=asked[asked.length-1].offsetTop-8;}
// Follow the page's light / dark choice (set on the page's <html> by the sun / moon button)
(function(){
  try{
    var root=window.parent.document.documentElement;
    var sync=function(){document.documentElement.setAttribute('data-theme',root.getAttribute('data-ac-theme')==='light'?'light':'dark');};
    sync();
    new MutationObserver(sync).observe(root,{attributes:true,attributeFilter:['data-ac-theme']});
  }catch(e){}
})();
</script>
</body></html>"""


def build_artbot_system_prompt():
    """Build ArtBot system prompt, injecting file context if a file has been analyzed."""
    ctx = st.session_state.get('artbot_file_context')
    if not ctx:
        return ARTBOT_SYSTEM_PROMPT

    lines = ["\n\n--- CURRENT FILE CONTEXT ---"]
    lines.append(f"The user has uploaded a file called '{ctx['filename']}' and ArtCheck has analyzed it.")
    lines.append(f"File type: {ctx.get('file_type', 'unknown')}")

    if ctx.get('width') and ctx.get('height'):
        lines.append(f"Dimensions: {ctx['width']} × {ctx['height']} px")
    if ctx.get('width_in') and ctx.get('height_in'):
        lines.append(f"Actual document size: {ctx['width_in']}\" × {ctx['height_in']}\" (the px dimensions above are the preview render, not the print size)")
    if ctx.get('size_kb'):
        lines.append(f"File size: {ctx['size_kb']} KB")
    if ctx.get('page_count') and ctx['page_count'] > 1:
        lines.append(f"Pages/artboards in file: {ctx['page_count']} (ArtCheck previewed and analyzed page {ctx.get('page_number') or 1} only)")

    # Vector files: what the converted PDF contains (paths vs embedded pictures)
    _pdf = ctx.get('pdf_export')
    if isinstance(_pdf, dict) and _pdf.get('ok'):
        if _pdf.get('images'):
            lines.append(f"Vector vs raster content: PARTLY RASTER. The file contains {_pdf['images']} embedded raster "
                         f"image(s) alongside {_pdf.get('paths', 0)} vector path(s). ArtCheck can count the raster images "
                         "but cannot tell which visual elements they are or what resolution they have; photo-like, "
                         "shaded or textured areas are the usual suspects. Embedded rasters do not scale like vector "
                         "art and cannot be color-separated for spot-color screen printing.")
        else:
            lines.append(f"Vector vs raster content: fully vector ({_pdf.get('paths', 0)} path(s), no embedded raster images).")

    # Raster-specific
    if ctx.get('dpi'):
        lines.append(f"DPI (metadata): {ctx['dpi']}")
    if ctx.get('color_mode'):
        lines.append(f"Color mode: {ctx['color_mode']}")
    if ctx.get('verdict'):
        verdict_map = {'good': 'Production Ready', 'marginal': 'Borderline Quality', 'poor': 'Not Suitable for Production'}
        lines.append(f"ArtCheck verdict: {verdict_map.get(ctx['verdict'], ctx['verdict'])}")
    if ctx.get('warnings'):
        lines.append(f"Warnings flagged: {'; '.join(ctx['warnings'])}")

    # Vector color data
    color_data = ctx.get('color_data')
    if color_data:
        color_mode = color_data.get('color_mode', '')
        if color_mode:
            lines.append(f"Color mode: {color_mode}")
        spots = color_data.get('spot_colors', [])
        if spots:
            spot_names = [str(s.get('label') or '')[:60] for s in spots if s.get('label')][:20]
            lines.append(f"Spot/Pantone colors found ({len(spots)}): {', '.join(spot_names) if spot_names else 'names not readable'}")
        fills = color_data.get('fills', [])
        if fills:
            fill_names = [str(f.get('label') or '')[:40] for f in fills if f.get('label')][:12]
            more = f" (first {len(fill_names)} listed)" if len(fills) > len(fill_names) else ""
            lines.append(f"Fill colors detected: {len(fills)}{more}: {'; '.join(fill_names)}")
        if color_data.get('gradients'):
            lines.append(f"Gradients detected: {len(color_data['gradients'])}")
        if color_data.get('warnings'):
            lines.append("Color warnings shown to the user: " + '; '.join(str(w)[:160] for w in color_data['warnings'][:6]))

    # Fonts
    fc = ctx.get('font_check')
    if fc:
        if fc.get('live_text'):
            font_names = ', '.join(
                f['name'] + (' (not embedded)' if f.get('embedded') is False else '') for f in fc.get('fonts', [])
            ) or 'font names not readable'
            lines.append(f"Font check: LIVE TEXT FOUND — fonts are NOT outlined. Fonts used: {font_names}")
        else:
            lines.append("Font check: no live text found (fonts are outlined or the file has no text)")

    # Decoration method the user is screening for, if they picked one
    if ctx.get('prescreen'):
        lines.append(ctx['prescreen'])

    # Embroidery
    emb = ctx.get('embroidery_info')
    if emb and isinstance(emb, dict):
        if emb.get('stitch_count'):
            lines.append(f"Stitch count: {emb['stitch_count']:,}")
        if emb.get('thread_changes') is not None:
            lines.append(f"Thread changes: {emb['thread_changes']}")
        if emb.get('thread_colors'):
            _hexes = [c.get('hex') for c in emb['thread_colors'] if isinstance(c, dict) and c.get('hex')][:16]
            lines.append(f"Thread colors in the file ({emb.get('unique_color_count', len(_hexes))} unique): {', '.join(_hexes)}")
        else:
            lines.append("Thread colors: the file carries no color data (normal for .dst); they are chosen at the machine.")

    lines.append("\nUse this file context to give specific, relevant advice. Reference the actual file details in your answers rather than speaking generically.")
    lines.append("--- END FILE CONTEXT ---")

    return ARTBOT_SYSTEM_PROMPT + "\n".join(lines)


def _artbot_sidebar_body():
    """Everything inside the ArtBot sidebar. Called by render_artbot_sidebar()."""
    st.markdown("### 🤖 Ask ArtBot")
    st.caption("Your AI production assistant - 20+ years of industry knowledge")
    file_ctx = st.session_state.get('artbot_file_context')
    if file_ctx:
        st.markdown(f"""
<div style="background:var(--ac-card-bg);border-radius:8px;padding:12px 14px;margin-bottom:10px;border-left:3px solid #28a745;">
  <div style="font-size:1.3rem;font-weight:bold;color:var(--ac-card-title);margin-bottom:6px;">🤖 I can see your file!</div>
  <div style="font-size:0.9rem;color:var(--ac-card-accent);margin-bottom:6px;">📁 <strong>{html.escape(str(file_ctx['filename']))}</strong></div>
  <div style="font-size:0.9rem;color:var(--ac-card-text);">Ask me anything about this specific file — I have all the details ArtCheck found.</div>
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown("""
<div style="background:var(--ac-card-bg);border-radius:8px;padding:12px 14px;margin-bottom:10px;border-left:3px solid #667eea;">
  <div style="font-size:1.3rem;font-weight:bold;color:var(--ac-card-title);margin-bottom:6px;">🤖 Got a file issue? Ask me.</div>
  <div style="font-size:0.95rem;color:var(--ac-card-sub);margin-bottom:8px;">📁 File fixes &nbsp;·&nbsp; 🎨 Color questions &nbsp;·&nbsp; 🧵 Decoration methods &nbsp;·&nbsp; ✅ Best practices</div>
  <div style="font-size:0.9rem;color:var(--ac-card-text);">Tell me what's going on and I'll tell you exactly how to tackle it and what to say to your customer.</div>
  <div style="font-size:0.78rem;color:var(--ac-card-hint);margin-top:6px;">💡 Generate a preview first and I'll be able to speak to your specific file.</div>
</div>
""", unsafe_allow_html=True)

    if "artbot_history" not in st.session_state:
        st.session_state.artbot_history = []
    if "artbot_input_key" not in st.session_state:
        st.session_state.artbot_input_key = 0
    if "artbot_pending" not in st.session_state:
        st.session_state.artbot_pending = None

    # Handle pending question (from example buttons or send)
    def _run_artbot(question):
        # The question may already be in the history: this is a second attempt
        # after the first one was cut off (see the note where this is called)
        _history = st.session_state.artbot_history
        if not (_history and _history[-1] == {"role": "user", "content": question}):
            _history.append({"role": "user", "content": question})
        # Test hook: the automated tests have no API key. When this variable points
        # at a file, its text is used as the answer and the API is not called.
        # It is never set in production.
        _fake_reply = os.environ.get("ARTBOT_FAKE_REPLY_FILE")
        if _fake_reply and os.path.exists(_fake_reply):
            with open(_fake_reply, encoding="utf-8") as _fh:
                st.session_state.artbot_history.append({"role": "assistant", "content": _fh.read()})
            return
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                try:
                    api_key = st.secrets.get("ANTHROPIC_API_KEY")
                except Exception:
                    pass
            # Without a timeout a stalled connection waits 10 minutes with no message
            client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=1)
            full_response = ""
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with client.messages.stream(
                        model="claude-sonnet-4-6",
                        max_tokens=1000,
                        system=build_artbot_system_prompt(),
                        messages=st.session_state.artbot_history[-8:].copy()
                    ) as stream:
                        for text in stream.text_stream:
                            full_response += text
                    break
                except Exception as retry_err:
                    if attempt < max_retries - 1 and any(x in str(retry_err).lower() for x in ["overloaded", "api_error", "500", "internal server"]):
                        import time
                        time.sleep(2)
                        full_response = ""
                        continue
                    raise retry_err
            if not full_response.strip():
                full_response = "⚠️ ArtBot returned an empty answer. Please ask again."
            # Only answer a question that is still waiting (never two answers to one question)
            if st.session_state.artbot_history and st.session_state.artbot_history[-1].get("role") == "user":
                st.session_state.artbot_history.append({"role": "assistant", "content": full_response})
        except Exception as e:
            st.session_state.artbot_history.append({"role": "assistant", "content": f"⚠️ Error: {str(e)}"})

    if st.session_state.artbot_pending:
        # The question stays pending until its answer is stored. Streamlit stops a
        # run the moment the user clicks anything else (or the browser reconnects),
        # and that used to leave the question in the chat with no answer and no
        # error. Now the next run simply asks again.
        q = st.session_state.artbot_pending
        with st.spinner("🤖 ArtBot is thinking..."):
            _run_artbot(q)
        if st.session_state.artbot_pending == q:
            st.session_state.artbot_pending = None
        st.rerun()

    # Chat history label
    st.markdown('<div style="font-size:0.75rem;color:#555;margin-bottom:3px;padding-left:2px;">💬 Conversation</div>', unsafe_allow_html=True)

    # Scrollable chat history box. Rendered in its own frame from Markdown,
    # with all user and model text escaped — see artbot_chat_page().
    import streamlit.components.v1 as _chat_components
    _chat_components.html(artbot_chat_page(st.session_state.artbot_history), height=466, scrolling=False)
    st.markdown('<div style="font-size:0.75rem;color:#555;margin-bottom:6px;padding-left:2px;">✏️ Type your question below</div>', unsafe_allow_html=True)

    # Input + send button — form allows Enter key to submit
    with st.form(key=f"artbot_form_{st.session_state.artbot_input_key}", clear_on_submit=True):
        q_col, btn_col = st.columns([5, 1])
        with q_col:
            question_input = st.text_input("q", placeholder="Ask anything...",
                label_visibility="collapsed")
        with btn_col:
            send = st.form_submit_button("➤", use_container_width=True, type="primary")

    # Example question chips — only show when no history
    if not st.session_state.artbot_history:
        st.caption("💡 Try one of these:")
        examples = [
            "What does 'fonts not outlined' mean?",
            "Difference between vector and raster?",
            "Can gradients be embroidered?",
            "Can I use customer website graphics for production?",
            "How do I handle a customer pushing back on art fees?",
        ]
        for ex in examples:
            if st.button(ex, use_container_width=True, key=f"ex_{ex}"):
                st.session_state.artbot_pending = ex
                st.rerun()

    if st.session_state.artbot_history:
        if st.button("🔄 Clear conversation", use_container_width=True):
            st.session_state.artbot_history = []
            st.session_state.artbot_pending = None
            st.session_state.artbot_input_key += 1
            st.rerun()

    if send and question_input.strip():
        st.session_state.artbot_pending = question_input.strip()
        st.session_state.artbot_input_key += 1
        st.rerun()

    st.markdown("""
<div style="background:var(--ac-warn-bg);border-radius:6px;padding:8px 12px;margin-top:8px;border-left:3px solid #cc4444;font-size:0.78rem;color:var(--ac-warn-text);">
⚠️ <strong style="color:var(--ac-warn-strong);">Disclaimer:</strong> ArtBot is an AI assistant and may occasionally make mistakes. Always confirm critical production specs with your decorator or supplier before production. Pricing guidance is approximate.
</div>
""", unsafe_allow_html=True)


_SIDEBAR_RENDERED = {'done': False}   # reset on every script run


def render_artbot_sidebar():
    """Draw the ArtBot sidebar. Call this AFTER the main area has rendered.

    ArtBot calls st.rerun() (send, example buttons, pending answer, clear). A
    rerun throws away the state of every widget that has not been rendered yet
    in that run. When the sidebar ran first, each ArtBot question made the file
    uploader forget its file (so its X stopped clearing results) and reset the
    Decoration Method Check. Rendering the sidebar last keeps all of that.
    It must be called before every early stop and once at the end of the script.
    """
    if _SIDEBAR_RENDERED['done']:
        return
    _SIDEBAR_RENDERED['done'] = True
    with st.sidebar:
        _artbot_sidebar_body()

# ============================================================================
# FILE UPLOAD SECTION
# ============================================================================

# Light / dark switch, top right (same sun and moon as the Mockup Builder).
# Streamlit has no Python call for changing the theme, so the button talks to
# the page directly: see THEME_TOGGLE_HTML.
import streamlit.components.v1 as _theme_components
with st.container(key="theme_toggle"):
    _theme_components.html(THEME_TOGGLE_HTML, height=44, scrolling=False)

st.markdown("""
<div style="padding:2rem 0 1.5rem 0;">
    <div style="font-size:2.8rem;font-weight:800;background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1.1;margin-bottom:0.5rem;">
        🎨 ArtCheck
    </div>
    <div style="font-size:1.25rem;color:var(--ac-tagline);font-weight:400;margin-bottom:1rem;">
        Instant art file screening for promotional products professionals.
    </div>
    <div style="font-size:0.95rem;color:#888;max-width:720px;line-height:1.7;">
        Built for sales reps and customer service teams who need quick answers on art files — 
        without waiting on the art department. Upload any vector, embroidery, or image file 
        to get an instant preview, color analysis, and production suitability check. 
        Ask ArtBot in the sidebar for expert guidance on file requirements, decoration methods, 
        and what to tell your customer.
    </div>
    <div style="font-size:0.9rem;color:var(--ac-tip);max-width:720px;line-height:1.6;margin-top:0.85rem;padding:0.65rem 0.9rem;background:rgba(102,126,234,0.08);border-left:3px solid #667eea;border-radius:4px;">
        💡 <strong>Need a customer mockup?</strong> Analyze your art file, download the trimmed transparent PNG, 
        then use the built-in <strong>Mockup Builder</strong> to drop it onto any product photo — 
        no SAGE login required.
    </div>
</div>
<hr style="border:none;border-top:1px solid var(--ac-rule);margin-bottom:1.5rem;">
""", unsafe_allow_html=True)

st.markdown("## 📁 Upload Your File")

def _clear_file_state():
    """Forget everything about the current file: preview, analysis, ArtBot's
    file context, Mockup Builder handoff and raster-in-PDF caches."""
    for _key in ('preview_image_bytes', 'preview_result', 'preview_color_data', 'preview_filename',
                 'preview_download_bytes', 'preview_pdf_bytes', 'preview_alpha_bytes', 'preview_image_bg',
                 '_page_autogen_attempt', 'artbot_file_context', '_raster_analysis', '_pdf_probe', '_xcf_flat',
                 '_sample_active', '_sample_autogen', 'preview_file_id', 'preview_effective_ext'):
        st.session_state.pop(_key, None)
    _old_token = st.session_state.pop('mockup_handoff_token', None)
    if _old_token:
        _get_mockup_handoff_store().pop(_old_token, None)
    for _k in list(st.session_state.keys()):
        if _k.startswith('raster_pdf_bytes_') or _k.startswith('raster_pdf_analysis_'):
            del st.session_state[_k]


def _on_uploader_change(uploader_key):
    """Runs only when the USER changes the uploader. If they removed the file
    with the X, clear the results too. (The uploader can also come back empty
    after an ArtBot rerun; no callback fires then, so cached results stay.)"""
    if st.session_state.get(uploader_key) is None:
        _clear_file_state()


SAMPLE_FILE = Path(__file__).parent / "static" / "sample_logo.ai"


class _SampleUpload:
    """The built-in sample logo, shaped like an uploaded file so the normal flow
    runs on it unchanged. The art is generated by tests/make_fixtures.make_sample_art()."""
    name = "sample_logo.ai"
    file_id = "sample"

    def __init__(self):
        self._data = SAMPLE_FILE.read_bytes()
        self.size = len(self._data)

    def getvalue(self):
        return self._data


_uploader_key = f"uploader_{st.session_state.get('file_uploader_key', 0)}"
uploaded_file = st.file_uploader(
    "🎨 Drag and drop your file here or click to browse",
    key=_uploader_key,
    type=['ai', 'eps', 'pdf', 'svg', 'cdr', 'xcf', 'indd', 'dst', 'pes', 'exp', 'jef', 'vp3', 'xxx', 'u01',
          'png', 'jpg', 'jpeg', 'gif', 'tiff', 'tif', 'bmp', 'webp'],
    help="Vector: .ai .eps .pdf .svg .cdr  •  Embroidery: .dst .pes .exp .jef .vp3 .xxx .u01  •  "
         "Images: .png .jpg .gif .tiff .bmp .webp .xcf  •  Up to 50MB",
    on_change=_on_uploader_change,
    args=(_uploader_key,),
)
st.caption("GIMP (.xcf) files are flattened to one image. InDesign (.indd) files show a small thumbnail only.")

# No file handy? One click loads a built-in logo and runs the whole check on it.
if uploaded_file:
    st.session_state.pop('_sample_active', None)       # a real upload replaces the sample
    st.session_state.pop('_sample_autogen', None)
elif st.session_state.get('_sample_active') and SAMPLE_FILE.exists():
    uploaded_file = _SampleUpload()
elif SAMPLE_FILE.exists():
    if st.button("✨ No file handy? Try a sample logo", key="try_sample_button",
                 help="Loads a small made-up logo so you can see the preview, colors, font check and decoration check."):
        _clear_file_state()
        st.session_state['_sample_active'] = True
        st.session_state['_sample_autogen'] = True
        st.rerun()

if uploaded_file:
    # Drop raster-in-PDF caches that belong to any previously uploaded file
    _current_suffix = f"_{uploaded_file.name}_{uploaded_file.size}"
    for _k in list(st.session_state.keys()):
        if (_k.startswith('raster_pdf_bytes_') or _k.startswith('raster_pdf_analysis_')) \
                and not _k.endswith(_current_suffix):
            del st.session_state[_k]

    # Forget the stored results when a different file arrives. Compared by name,
    # size and upload id: a re-exported file usually keeps its name.
    _upload_id = f"{uploaded_file.name}|{uploaded_file.size}|{getattr(uploaded_file, 'file_id', '')}"
    if st.session_state.get('preview_filename') and \
            st.session_state.get('preview_file_id', _upload_id) != _upload_id:
        _keep_sample = st.session_state.get('_sample_active'), st.session_state.get('_sample_autogen')
        _clear_file_state()
        if _keep_sample[0]:
            st.session_state['_sample_active'], st.session_state['_sample_autogen'] = _keep_sample

    # InDesign: cannot be rendered without InDesign. Show the small page preview
    # InDesign saves inside the file (when there is one) plus what to ask for.
    if uploaded_file.name.lower().endswith('.indd'):
        _indd_thumb = None
        try:
            _indd_thumb = indd_tools.thumbnail(uploaded_file.getvalue())
        except Exception:
            _indd_thumb = None
        if _indd_thumb:
            st.warning("### 📄 InDesign file: thumbnail only")
            st.image(_indd_thumb['image'], width=min(512, _indd_thumb['width']))
            _saved = f" on {_indd_thumb['saved']}" if _indd_thumb.get('saved') else ""
            st.caption(f"Small preview ({_indd_thumb['width']} × {_indd_thumb['height']} px) saved inside the file by "
                       f"{_indd_thumb['app']}{_saved}. It shows the first page and may not include the latest edits. "
                       "It is not usable for production.")
            st.info("""
        **ArtCheck cannot check size, colors or fonts in an InDesign (.indd) file.**

        **For a full check, ask for an export from InDesign as:**
        - **PDF** (File → Export → Adobe PDF) - BEST for print
        - **EPS** (File → Export → EPS)
        """)
        else:
            st.error("### 📄 InDesign Files Not Supported")
            st.warning("""
        **InDesign (.indd) files cannot be processed directly.**
    
        **Please export from InDesign as:**
        - **PDF** (File → Export → Adobe PDF) - BEST for print
        - **AI** (File → Export → Adobe Illustrator)
        - **EPS** (File → Export → EPS)
    
        Then upload the exported file to ArtCheck!
        """)
        render_artbot_sidebar()
        st.stop()

    # GIMP: flatten the layers to one image (xcf_tools) and treat it like any other image
    _xcf_flat = None
    if uploaded_file.name.lower().endswith('.xcf'):
        _xcf_id = f"{uploaded_file.name}|{uploaded_file.size}|{getattr(uploaded_file, 'file_id', '')}"
        _xcf_flat = st.session_state.get('_xcf_flat')
        if not isinstance(_xcf_flat, dict) or _xcf_flat.get('id') != _xcf_id:
            with st.spinner("Opening GIMP file..."):
                _xcf_flat = flatten_gimp_upload(uploaded_file.getvalue(), _xcf_id)
            st.session_state['_xcf_flat'] = _xcf_flat
        if _xcf_flat.get('error'):
            st.error("### 🖼️ This GIMP file could not be opened")
            st.warning(f"""
        **{_xcf_flat['error']}**

        **Please export from GIMP as:**
        - **PNG** (File → Export As → name it .png) - keeps the transparent background
        - **PDF** (File → Export As → name it .pdf)

        Then upload the exported file to ArtCheck!
        """)
            render_artbot_sidebar()
            st.stop()

    col_succ, col_clear = st.columns([4, 1])
    with col_succ:
        if isinstance(uploaded_file, _SampleUpload):
            st.success("✓ Sample loaded: **sample_logo.ai** — a made-up logo with two Pantone colors and live text")
        else:
            st.success(f"✓ Uploaded: **{uploaded_file.name}** ({uploaded_file.size / 1024 / 1024:.2f} MB)")
    with col_clear:
        if st.button("🔄 New File", use_container_width=True, help="Clear this file and upload a new one"):
            st.session_state['file_uploader_key'] = st.session_state.get('file_uploader_key', 0) + 1
            _clear_file_state()
            st.rerun()

    if _xcf_flat:
        _info = _xcf_flat['info']
        _layers = f"{_info['layers']} layer{'s' if _info['layers'] != 1 else ''}"
        _hidden = f" ({_info['hidden']} hidden layer{'s' if _info['hidden'] != 1 else ''} left out)" if _info['hidden'] else ""
        st.info(f"🖼️ GIMP file — {_layers} flattened into one image{_hidden}, analyzing for production suitability...")
        if _info.get('approximate'):
            st.caption("⚠️ This file uses effects ArtCheck draws as plain layers ("
                       + ", ".join(_info['approximate']) + "). Colors in those areas may look different in GIMP.")
        st.image(_xcf_flat['display'], caption="Flattened preview", use_container_width=True)
        _xcf_stem = uploaded_file.name.rsplit('.', 1)[0]
        st.download_button(
            label="⬇️ Download PNG",
            data=_xcf_flat['png'],
            file_name=f"{_xcf_stem}.png",
            mime="image/png",
            use_container_width=True,
            key="download_xcf_png_button",
            help="The flattened image at full size, with its transparent background.",
        )
        analysis = _xcf_flat['analysis']
        st.session_state['artbot_file_context'] = {
            'filename': uploaded_file.name,
            'file_type': 'raster',
            'width': analysis.get('width_px'),
            'height': analysis.get('height_px'),
            'dpi': analysis.get('dpi'),
            'color_mode': analysis.get('color_mode'),
            'verdict': analysis.get('verdict'),
            'warnings': analysis.get('warnings', []) + [
                f"GIMP .xcf file, {_layers} flattened by ArtCheck{_hidden}"],
            'size_kb': round(uploaded_file.size / 1024, 2),
        }
        render_raster_results(analysis, uploaded_file.name)
        render_decoration_check(decoration_rules.facts_from_raster(analysis, uploaded_file.name), uploaded_file.name)
        st.markdown("---")
        _render_mockup_builder_button(_xcf_flat['png'], _xcf_stem)
        render_artbot_sidebar()
        st.stop()

    # PDF / AI: page picker for multi-page files, then check whether the chosen
    # page is only a picture (raster-in-PDF) before the normal vector flow
    _page_index = 0
    _page_total = 1
    # What to process the file as: an .ai saved in PostScript form is handled as EPS
    _eff_suffix = effective_suffix(uploaded_file.name, uploaded_file.getvalue())
    _eff_name = uploaded_file.name if _eff_suffix == Path(uploaded_file.name).suffix.lower() \
        else uploaded_file.name.rsplit('.', 1)[0] + _eff_suffix
    if _eff_name != uploaded_file.name:
        st.caption("ℹ️ This .ai file is saved in Illustrator's PostScript (EPS) form, so ArtCheck reads it as an EPS: "
                   "all artboards appear together in one image.")
    if _eff_suffix in ['.pdf', '.ai']:
        _lazy_pdf = _LazyPdf(uploaded_file)
        try:
            _probe_id = f"{uploaded_file.name}|{uploaded_file.size}|{getattr(uploaded_file, 'file_id', '')}"
            _probe = st.session_state.get('_pdf_probe')
            if not isinstance(_probe, dict) or _probe.get('id') != _probe_id:
                _probe = {'id': _probe_id, 'pages': None, 'raster': {}}
            if _probe['pages'] is None:
                _probe['pages'] = _lazy_pdf.doc().page_count or 1
            _page_total = _probe['pages']
            if _page_total > 1:
                _page_index = st.selectbox(
                    "Page", list(range(_page_total)),
                    format_func=lambda i: f"Page {i + 1} of {_page_total}",
                    key=f"page_pick_{uploaded_file.name}_{uploaded_file.size}",
                    help="This file has more than one page (or artboard). Pick the one to preview and analyze.",
                )
            if _page_index not in _probe['raster']:
                _probe_page = _lazy_pdf.doc()[_page_index]
                _probe['raster'][_page_index] = (len(_probe_page.get_images()) > 0
                                                 and len(_probe_page.get_drawings()) < 3)
            st.session_state['_pdf_probe'] = _probe
            _is_raster_pdf = _probe['raster'][_page_index]
            if _is_raster_pdf:
                st.info("📷 Raster image detected inside PDF — analyzing for production suitability...")
                # Extract and cache image bytes in session state so bg changes don't re-extract
                _cache_key = f"raster_pdf_bytes_p{_page_index}_{uploaded_file.name}_{uploaded_file.size}"
                if _cache_key not in st.session_state:
                    _doc = _lazy_pdf.doc()
                    _xref = _doc[_page_index].get_images()[0][0]
                    _base_image = _doc.extract_image(_xref)
                    st.session_state[_cache_key] = (_base_image["image"], _base_image["ext"])
                _lazy_pdf.close()
                _img_bytes, _img_ext = st.session_state[_cache_key]
                # Background selector
                if 'bg_type_raster_pdf' not in st.session_state:
                    st.session_state.bg_type_raster_pdf = 'auto'
                _btn_labels = [("🔄 Auto", "auto"), ("☀️ Light", "light"), ("🌙 Dark", "dark"), ("⬜ Transparent", "transparent")]
                _cols = st.columns(4)
                for _col, (_label, _val) in zip(_cols, _btn_labels):
                    with _col:
                        _selected = st.session_state.bg_type_raster_pdf == _val
                        if st.button(_label, use_container_width=True, type="primary" if _selected else "secondary", key=f"rpdf_bg_{_val}"):
                            st.session_state.bg_type_raster_pdf = _val
                            st.rerun()
                st.caption(f"Background: **{st.session_state.bg_type_raster_pdf.title()}**")
                # Downsize first to save memory, then the same backgrounds as every other
                # preview (Auto used to mean plain white here, and Transparent no checkerboard)
                _preview_img = Image.open(io.BytesIO(_img_bytes)).convert('RGBA')
                _max_dim = 1200
                if max(_preview_img.size) > _max_dim:
                    _ratio = _max_dim / max(_preview_img.size)
                    _preview_img = _preview_img.resize(
                        (int(_preview_img.width * _ratio), int(_preview_img.height * _ratio)), Image.LANCZOS)
                _preview_img = compose_background(_preview_img, st.session_state.bg_type_raster_pdf)
                st.image(_preview_img, caption="Extracted raster image from PDF", use_container_width=True)
                # Run raster analysis once (not again on background button clicks)
                _analysis_key = f"raster_pdf_analysis_p{_page_index}_{uploaded_file.name}_{uploaded_file.size}"
                if _analysis_key not in st.session_state:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{_img_ext}') as _img_file:
                        _img_file.write(_img_bytes)
                        _img_tmp = _img_file.name
                    try:
                        st.session_state[_analysis_key] = RasterAnalyzer().analyze(_img_tmp)
                    finally:
                        if os.path.exists(_img_tmp):
                            os.unlink(_img_tmp)
                _analysis = st.session_state[_analysis_key]
                # Store ArtBot context
                st.session_state['artbot_file_context'] = {
                    'filename': uploaded_file.name,
                    'file_type': 'raster-in-PDF',
                    'width': _analysis.get('width_px'),
                    'height': _analysis.get('height_px'),
                    'dpi': _analysis.get('dpi'),
                    'color_mode': _analysis.get('color_mode'),
                    'verdict': _analysis.get('verdict'),
                    'warnings': _analysis.get('warnings', []),
                    'size_kb': round(uploaded_file.size / 1024, 2),
                }
                render_raster_results(_analysis, uploaded_file.name)
                render_decoration_check(decoration_rules.facts_from_raster(_analysis, uploaded_file.name), uploaded_file.name)
                # Mockup builder uses the extracted raster bytes
                st.markdown("---")
                _filename_stem = uploaded_file.name.rsplit('.', 1)[0]
                _render_mockup_builder_button(_img_bytes, _filename_stem)
                render_artbot_sidebar()
                st.stop()
        except Exception:
            pass
        finally:
            _lazy_pdf.close()

    # Handle raster images separately
    raster_analyzer = RasterAnalyzer()
    if raster_analyzer.is_raster(uploaded_file.name):
        st.info("📷 Raster image detected — analyzing for production suitability...")

        # Show the image as preview
        st.image(uploaded_file, caption="Your Image", use_container_width=True)

        # Analyze once per uploaded file, not again on every click
        _raster_id = f"{uploaded_file.name}|{uploaded_file.size}|{getattr(uploaded_file, 'file_id', '')}"
        _cached_analysis = st.session_state.get('_raster_analysis')
        if isinstance(_cached_analysis, dict) and _cached_analysis.get('id') == _raster_id:
            analysis = _cached_analysis['analysis']
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name
            try:
                analysis = raster_analyzer.analyze(tmp_path)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            st.session_state['_raster_analysis'] = {'id': _raster_id, 'analysis': analysis}

        # Store context for ArtBot (the sidebar is drawn after this, so it sees it straight away)
        st.session_state['artbot_file_context'] = {
            'filename': uploaded_file.name,
            'file_type': 'raster',
            'width': analysis.get('width_px'),
            'height': analysis.get('height_px'),
            'dpi': analysis.get('dpi'),
            'color_mode': analysis.get('color_mode'),
            'verdict': analysis.get('verdict'),
            'warnings': analysis.get('warnings', []),
            'size_kb': round(uploaded_file.size / 1024, 2),
        }

        render_raster_results(analysis, uploaded_file.name)
        render_decoration_check(decoration_rules.facts_from_raster(analysis, uploaded_file.name), uploaded_file.name)

        # Mockup builder button — uses the original PNG bytes
        if uploaded_file.name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.tiff', '.tif', '.bmp', '.webp')):
            st.markdown("---")
            _filename_stem = uploaded_file.name.rsplit('.', 1)[0]
            _render_mockup_builder_button(uploaded_file.getvalue(), _filename_stem)

        render_artbot_sidebar()
        st.stop()

    # Background options — use session state so selection survives the Generate button click
    if 'bg_type' not in st.session_state:
        st.session_state.bg_type = 'auto'

    bg_type = st.session_state.bg_type

    # Highlighted background selector buttons
    btn_labels = [("🔄 Auto", "auto"), ("☀️ Light", "light"), ("🌙 Dark", "dark"), ("⬜ Transparent", "transparent")]
    cols = st.columns(4)
    for col, (label, val) in zip(cols, btn_labels):
        with col:
            selected = bg_type == val
            btn_style = "primary" if selected else "secondary"
            if st.button(label, use_container_width=True, type=btn_style):
                st.session_state.bg_type = val
                st.rerun()

    bg_type = st.session_state.bg_type
    st.caption(f"Background: **{bg_type.title()}** — switches instantly once a preview is showing")

    # Picking a different page of a file that already has a preview regenerates
    # it automatically. The attempt marker stops a failing page from looping.
    _file_id = f"{uploaded_file.name}|{uploaded_file.size}"
    _shown = st.session_state.get('preview_result') or {}
    _page_changed = (
        _page_total > 1
        and st.session_state.get('preview_image_bytes')
        and st.session_state.get('preview_filename') == uploaded_file.name
        and (_shown.get('page_number') or 1) != _page_index + 1
        and st.session_state.get('_page_autogen_attempt') != (_file_id, _page_index)
    )

    # Generate Preview (also runs by itself once, right after the sample is loaded)
    _sample_go = bool(st.session_state.pop('_sample_autogen', False))
    if st.button("🚀 Generate Preview", use_container_width=True, type="primary") or _page_changed or _sample_go:
        st.session_state['_page_autogen_attempt'] = (_file_id, _page_index)
        with st.spinner("Generating preview..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=_eff_suffix) as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name

            # Multi-page PDF / AI: analyze a one-page copy of the chosen page
            analysis_path = tmp_path
            _page_path = None
            if _page_total > 1:
                _page_path = extract_pdf_page(tmp_path, _page_index)
                if _page_path:
                    analysis_path = _page_path

            generator = get_preview_generator()
            # ONE render, with transparency. The background is added afterwards
            # (compose_background), which is what makes background changes instant.
            result = generator.generate_preview(analysis_path, 'transparent_alpha')
            if result:
                # Report the size of the file the user uploaded, not of the preview PNG
                result['size_kb'] = round(uploaded_file.size / 1024, 2)
                if _page_total > 1:
                    result['page_count'] = _page_total
                    result['page_number'] = (_page_index + 1) if _page_path else 1

            _dl_bytes = None
            _alpha_bytes = None
            if result and os.path.exists(result['image']):
                import io as _io
                _full = Image.open(result['image'])
                if _full.mode != 'RGBA':
                    _full = _full.convert('RGBA')
                # Download version: trim transparent edges so it drops cleanly onto mockups
                try:
                    _dl_img = _full
                    _bbox = _dl_img.split()[3].getbbox()
                    if _bbox:
                        _dl_img = _dl_img.crop(_bbox)
                    _dl_buf = _io.BytesIO()
                    _dl_img.save(_dl_buf, format='PNG')   # optimize=True was ~3x slower for ~1% smaller
                    _dl_bytes = _dl_buf.getvalue()
                except Exception:
                    # Fall back to untrimmed bytes if anything goes wrong
                    with open(result['image'], 'rb') as _dlf:
                        _dl_bytes = _dlf.read()
                # Screen version: at most 1200 px, still transparent. Full-res can be
                # 20-30MB, which is too much to keep in session memory.
                _max = 1200
                _small = _full
                if max(_small.width, _small.height) > _max:
                    _ratio = _max / max(_small.width, _small.height)
                    _small = _small.resize((int(_small.width * _ratio), int(_small.height * _ratio)), Image.LANCZOS)
                _alpha_buf = _io.BytesIO()
                _small.save(_alpha_buf, format='PNG')
                _alpha_bytes = _alpha_buf.getvalue()

            color_data = None
            file_ext = _eff_suffix
            if file_ext in [".pdf", ".ai", ".eps", ".svg"]:
                extractor = get_color_extractor()
                color_data = extractor.extract(analysis_path)

            # Live-text / fonts-not-outlined check (same file types as color analysis)
            if result and file_ext in [".pdf", ".ai", ".eps", ".svg"]:
                result['font_check'] = FontChecker().check(analysis_path)

            # Vector PDF version of EPS / AI / SVG / CDR files (never built from the
            # preview image). Always the whole file, not just the page being viewed.
            _pdf_bytes = None
            if result and PdfConverter().can_convert(_eff_name):
                _pdf_bytes, result['pdf_export'] = PdfConverter().convert(tmp_path)
                if (result.get('pdf_export') or {}).get('ok') and result.get('file_type'):
                    result['file_type'] = mixed_label(result['file_type'], result['pdf_export'].get('images'))

            for _tmp_file in (tmp_path, _page_path):
                if _tmp_file and os.path.exists(_tmp_file):
                    os.unlink(_tmp_file)
            _CDR_CONVERSIONS.clear()
            _EPS_PDFS.clear()

            # The preview PNG is now in memory — remove it from /tmp so files
            # don't pile up on the server for the life of the container.
            try:
                if result and result.get('image') and os.path.exists(result['image']):
                    os.unlink(result['image'])
            except Exception:
                pass

        # Store everything in session state OUTSIDE the spinner
        if result and _alpha_bytes:
            st.session_state['preview_alpha_bytes'] = _alpha_bytes
            st.session_state['preview_image_bytes'] = compose_preview_bytes(_alpha_bytes, bg_type)
            st.session_state['preview_image_bg'] = bg_type
            st.session_state['preview_download_bytes'] = _dl_bytes
            st.session_state['preview_pdf_bytes'] = _pdf_bytes  # None unless EPS / AI / SVG / CDR
            st.session_state['preview_result'] = result
            st.session_state['preview_color_data'] = color_data
            st.session_state['preview_filename'] = uploaded_file.name
            st.session_state['preview_file_id'] = _upload_id
            st.session_state['preview_effective_ext'] = _eff_suffix
            st.session_state['artbot_file_context'] = {
                'filename': uploaded_file.name,
                'file_type': result.get('file_type', 'unknown'),
                'width': result.get('width'),
                'height': result.get('height'),
                'size_kb': result.get('size_kb'),
                'width_in': result.get('width_in'),
                'height_in': result.get('height_in'),
                'page_count': result.get('page_count'),
                'page_number': result.get('page_number'),
                'font_check': result.get('font_check'),
                'pdf_export': result.get('pdf_export'),
                'color_data': color_data,
                'embroidery_info': result.get('embroidery_info'),
            }
            st.rerun()  # Rerun so session state block handles all rendering cleanly
        # No rerun when the preview could not be made: a rerun here used to wipe the
        # "Could not convert file" message, so a bad file looked like nothing happened.

# Render stored preview from session state (persists across ArtBot reruns)
if st.session_state.get('preview_image_bytes') and st.session_state.get('preview_result'):
    result = st.session_state['preview_result']
    color_data = st.session_state.get('preview_color_data')
    # Instant background switching: re-compose the stored transparent preview
    # whenever the chosen background differs from the one currently shown
    _want_bg = st.session_state.get('bg_type', 'auto')
    if st.session_state.get('preview_alpha_bytes') and st.session_state.get('preview_image_bg') != _want_bg:
        try:
            st.session_state['preview_image_bytes'] = compose_preview_bytes(st.session_state['preview_alpha_bytes'], _want_bg)
            st.session_state['preview_image_bg'] = _want_bg
        except Exception:
            pass
    img_bytes = st.session_state['preview_image_bytes']
    st.markdown('<div class="success-box">✅ Preview generated successfully!</div>', unsafe_allow_html=True)
    if (result.get('page_count') or 1) > 1:
        if result.get('page_number'):
            st.info(f"📄 This file has **{result['page_count']} pages**. Showing **page {result['page_number']}** — the preview, "
                    "size, fonts and colors below are for that page. Use the **Page** menu above to look at another one.")
        else:
            st.info(f"📄 This file has **{result['page_count']} pages**. ArtCheck previews and analyzes **page 1 only** — "
                    "the preview, size and colors below do not cover the other pages.")
    col1, col2 = st.columns([2, 1])
    with col1:
        import base64, streamlit.components.v1 as _components
        _b64 = base64.b64encode(img_bytes).decode()
        _pz = """<!DOCTYPE html>
<html><head><style>
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#111;overflow:hidden;width:100%;height:490px;}
#viewport{width:100%;height:490px;overflow:hidden;position:relative;
  background:#111;border-radius:8px;cursor:grab;}
#viewport.grabbing{cursor:grabbing;}
#img{position:absolute;top:50%;left:50%;transform-origin:center center;
  max-width:none;display:block;user-select:none;pointer-events:none;}
#controls{position:absolute;top:8px;right:8px;display:flex;gap:4px;z-index:10;}
.ctrl-btn{background:#222;color:#aaa;border:1px solid #444;border-radius:4px;
  padding:4px 10px;font-size:0.75rem;cursor:pointer;font-family:sans-serif;}
.ctrl-btn:hover{background:#333;color:#fff;}
/* light version: the frame around the preview follows the page's sun / moon choice */
html[data-theme="light"] body,html[data-theme="light"] #viewport{background:#eceef3;}
html[data-theme="light"] .ctrl-btn{background:#fff;color:#555;border-color:#c5c9d3;}
html[data-theme="light"] .ctrl-btn:hover{background:#f1f2f6;color:#111;}
</style></head><body>
<script>
(function(){try{var r=window.parent.document.documentElement;
var f=function(){document.documentElement.setAttribute('data-theme',r.getAttribute('data-ac-theme')==='light'?'light':'dark');};
f();new MutationObserver(f).observe(r,{attributes:true,attributeFilter:['data-ac-theme']});}catch(e){}})();
</script>
<div id="viewport">
  <img id="img" src="data:image/png;base64,IMG_B64" draggable="false"/>
  <div id="controls">
    <button class="ctrl-btn" onclick="zoomIn()">+</button>
    <button class="ctrl-btn" onclick="zoomOut()">-</button>
    <button class="ctrl-btn" onclick="reset()">Reset</button>
  </div>
</div>
<script>
var vp=document.getElementById('viewport');
var img=document.getElementById('img');
var tx=0,ty=0,dragging=false,sx=0,sy=0,stx=0,sty=0;
var vw=vp.offsetWidth||760, vh=vp.offsetHeight||490;
var iw=img.naturalWidth||img.width||760, ih=img.naturalHeight||img.height||490;
var scale=Math.min(vw/iw, vh/ih, 1);
function apply(){
  img.style.transform='translate(calc(-50% + '+tx+'px), calc(-50% + '+ty+'px)) scale('+scale+')';
}
img.onload=function(){
  iw=img.naturalWidth; ih=img.naturalHeight;
  scale=Math.min(vw/iw, vh/ih, 1);
  apply();
};
apply();
vp.addEventListener('wheel',function(e){
  e.preventDefault();
  var delta=e.deltaY<0?1.1:0.9;
  scale=Math.min(8,Math.max(0.2,scale*delta));
  apply();
},{passive:false});
vp.addEventListener('mousedown',function(e){
  dragging=true;sx=e.clientX;sy=e.clientY;stx=tx;sty=ty;
  vp.classList.add('grabbing');
});
window.addEventListener('mousemove',function(e){
  if(!dragging)return;
  tx=stx+(e.clientX-sx);ty=sty+(e.clientY-sy);apply();
});
window.addEventListener('mouseup',function(){dragging=false;vp.classList.remove('grabbing');});
vp.addEventListener('touchstart',function(e){
  if(e.touches.length===1){
    dragging=true;sx=e.touches[0].clientX;sy=e.touches[0].clientY;stx=tx;sty=ty;
  }
},{passive:true});
vp.addEventListener('touchmove',function(e){
  if(dragging&&e.touches.length===1){
    tx=stx+(e.touches[0].clientX-sx);ty=sty+(e.touches[0].clientY-sy);apply();
  }
},{passive:true});
vp.addEventListener('touchend',function(){dragging=false;});
var fitScale=scale;
function zoomIn(){scale=Math.min(8,scale*1.25);apply();}
function zoomOut(){scale=Math.max(0.1,scale/1.25);apply();}
function reset(){scale=fitScale;tx=0;ty=0;apply();}
</script>
</body></html>""".replace("IMG_B64", _b64)
        _components.html(_pz, height=495, scrolling=False)
        st.caption("Your Preview")
    with col2:
        st.markdown("### Preview Info")
        if result.get('width'):
            st.metric("Dimensions (px)", f"{result['width']} × {result['height']}")
            if result.get('width_in') and result.get('height_in'):
                # Real document size (PDF/AI page, SVG with units, embroidery stitch area)
                st.metric("Size (inches)", f'{result["width_in"]}" x {result["height_in"]}"')
            elif result.get('size_note') == 'scalable':
                st.metric("Size (inches)", "Scalable")
                st.caption("No fixed size is set in this SVG. Vector art can be scaled to any print size.")
            elif result.get('size_note') == 'unknown':
                st.metric("Size (inches)", "Not detected")
                st.caption("ArtCheck could not read a physical size from this file.")
            else:
                w_in = round(result['width'] / 300, 2)
                h_in = round(result['height'] / 300, 2)
                st.metric("Size (inches)", f'{w_in}" x {h_in}"')
        if result.get('size_kb'):
            _kb = result['size_kb']
            st.metric("File Size", f"{_kb / 1024:.2f} MB" if _kb >= 1024 else f"{_kb} KB")
        if result.get('file_type'):
            _ft = result['file_type']
            st.metric("File Type", _ft[:1].upper() + _ft[1:])
            if 'embedded raster' in result.get('file_type', '').lower():
                st.warning("""
⚠️ **This file contains a raster image, not vector paths.**

Despite the file extension, this is not a true vector file. It's a raster image (like a JPG or PNG) saved inside a vector wrapper.

**What to tell your customer:**
> "This file appears to be a raster image saved as a vector file. For best print quality, we need the original vector file (.ai or .eps) from your designer, or a high-resolution PNG/JPG at 300 DPI or higher."
                """)

        if result.get('embroidery_info'):
            emb = result['embroidery_info']
            st.markdown("### 🧵 Embroidery Info")
            st.metric("Stitch Count", f"{emb['stitch_count']:,}")
            st.metric("Thread Changes", emb['thread_changes'])
            st.metric("Size", f"{emb['width_mm']}mm × {emb['height_mm']}mm")
            thread_colors = emb.get('thread_colors', [])
            unique_count = emb.get('unique_color_count', 0)
            if thread_colors and unique_count > 0:
                st.markdown(f"**Thread Colors** ({unique_count} unique)")
                swatch_html = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:4px;">'
                for c in thread_colors:
                    border = "2px solid #888" if c["is_duplicate"] else "2px solid #444"
                    swatch_html += (
                        f'<div style="text-align:center;">'
                        f'<div style="background:{c["hex"]};width:36px;height:36px;'
                        f'border-radius:4px;border:{border};"></div>'
                        f'<div style="font-size:0.65rem;color:var(--ac-muted);margin-top:2px;">{c["hex"]}</div>'
                        f'</div>'
                    )
                swatch_html += '</div>'
                st.markdown(swatch_html, unsafe_allow_html=True)
        st.markdown("---")
        _dl_data = st.session_state.get('preview_download_bytes') or img_bytes
        st.download_button(
            label="⬇️ Download PNG (transparent background)",
            data=_dl_data,
            file_name=f"{st.session_state.get('preview_filename', 'preview').rsplit('.', 1)[0]}_preview.png",
            mime="image/png",
            use_container_width=True
        )
        _filename_stem = st.session_state.get('preview_filename', 'artwork').rsplit('.', 1)[0]
        render_pdf_export(st.session_state.get('preview_pdf_bytes'), result.get('pdf_export'), _filename_stem,
                          live_text=bool((result.get('font_check') or {}).get('live_text')))
        _render_mockup_builder_button(_dl_data, _filename_stem)
        if st.button("🔄 Upload New File", use_container_width=True):
            _clear_file_state()
            st.session_state['file_uploader_key'] = st.session_state.get('file_uploader_key', 0) + 1
            st.rerun()
    render_decoration_check(decoration_rules.facts_from_vector(result, color_data),
                            st.session_state.get('preview_filename', ''))
    render_font_check(result.get('font_check'))
    if color_data:
        stored_filename = st.session_state.get('preview_filename', '')
        render_color_results(color_data, st.session_state.get('preview_effective_ext')
                             or Path(stored_filename).suffix.lower())

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>Built with ❤️ for promotional products professionals</p>
    <p>🤖 AI-powered answers • 📁 Instant previews • ⏱️ Save 15+ hours/week</p>
    <p style="font-size:0.78rem;color:#555;margin-top:8px;">🔒 <strong>Privacy:</strong> ArtCheck does not store your uploaded files. Files are processed temporarily and discarded immediately. ArtBot conversations are powered by the Anthropic API.</p>
    <p style="margin-top:10px;">
        <a href="https://ko-fi.com/artchecktips" target="_blank" style="background:#FF5E5B;color:#fff;padding:6px 16px;border-radius:20px;text-decoration:none;font-size:0.85rem;font-weight:bold;">☕ Buy me a coffee</a>
        &nbsp;&nbsp;
        <a href="mailto:artchecksupport@gmail.com" style="color:#888;font-size:0.82rem;text-decoration:none;">📧 Contact & Contract Work</a>
        &nbsp;&nbsp;
        <a href="https://github.com/Shernandez520/artcheck/issues" target="_blank" style="color:#888;font-size:0.82rem;text-decoration:none;">🐛 Report a Bug</a>
    </p>
    <p style="font-size:0.75rem;color:#555;margin-top:4px;">ArtCheck is free — support keeps it that way.</p>
</div>
""", unsafe_allow_html=True)

# ArtBot sidebar is drawn last on purpose — see render_artbot_sidebar()
render_artbot_sidebar()

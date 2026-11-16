# ArtCheck — Development Context

> Public repo note: keep this file technical. Business strategy, legal notes,
> beta tester info, and anything personal lives OUTSIDE this repository.
> Never paste tokens or API keys into files or commit messages.

## What This Is
ArtCheck is a web app for promotional products suppliers that automates art
file screening (previews, color analysis, production suitability) before files
reach the art department.

**Live app:** https://www.artcheck.app (Railway — NOT Streamlit Cloud)
**Main file:** `app_with_embroidery.py` — this is what runs in production.

## Tech Stack
- **Python** + **Streamlit 1.43.2** (pinned — do NOT unpin, 1.55 broke the app)
- **PyMuPDF (fitz)** — PDF/AI renderer (dynamic scale: 10x, 1200px min, capped at 4000px longest side via `RENDER_MAX_PX` — uncapped renders of large pages exhaust memory; alpha=True for bg support)
- **Ghostscript** — EPS renderer (pngalpha device) + EPS color extraction (GS→PDF→fitz pipeline)
- **CairoSVG** — SVG renderer; **pdf2image** — PDF fallback
- **pyembroidery** — embroidery files; **Pillow** — compositing
- **Anthropic Claude API** — ArtBot; key in Railway env var `ANTHROPIC_API_KEY`
- **markdown-it-py 3.0.0** — renders ArtBot's Markdown answers to HTML (pure Python)

## Supported File Types
- Vector: .ai, .eps, .pdf, .svg, .cdr
- Embroidery: .dst, .pes, .exp, .jef, .vp3, .xxx, .u01
- Raster: .png, .jpg, .jpeg, .gif, .tiff, .bmp, .webp, and GIMP .xcf (flattened)
- Thumbnail only: .indd (the preview InDesign saves inside the file). Size,
  colors and fonts cannot be checked; the page says so and asks for an export.

## Architecture

### PreviewGenerator
EPS: Ghostscript (`pngalpha`, `-dEPSCrop`) → fitz fallback. 300 DPI unless that
would pass `RENDER_MAX_PX`: `_eps_render_dpi()` reads the bounding box and lowers
the resolution (a 64" × 28" stock-art EPS was a 160-megapixel render), and the
size in inches then comes from the bounding box instead of pixels / 300.
**.ai saved in PostScript form:** Illustrator can write an .ai that starts with
`%!PS-Adobe ... EPSF` instead of the usual PDF (stock-art sites deliver these).
fitz cannot open it, which showed "Could not convert file". `effective_suffix()`
sniffs the upload and the whole flow (temp file suffix, colors, fonts, PDF
export, no page picker) treats it as `.eps`; `preview_effective_ext` keeps that
for the stored results. Decide file type with `_eff_suffix`, not the file name.
PDF/AI: fitz (dynamic scale, alpha=True) → pdf2image fallback.
SVG: detect embedded raster → fitz or CairoSVG.
CDR: `convert_cdr()` → `cdr2xhtml` (libcdr) → `cdr_tools.svg_pages_from_libcdr()`
→ PDF (MuPDF's SVG reader via `fitz.open(filetype='svg').convert_to_pdf()`,
about 5x faster than CairoSVG on big drawings and the same picture; CairoSVG is
the fallback when that yields an empty page) → rendered with fitz. cdr2xhtml prints an XHTML page with
`svg:`-prefixed drawings, NOT plain SVG; feeding it straight to CairoSVG fails
("SVG size is undefined") and fitz then lays it out as a tall HTML page. Page 1
only; real page size comes from the converted PDF. One conversion per run is
shared by both preview renders and the PDF download (`_CDR_CONVERSIONS`).
Embroidery: pyembroidery → PIL visualization.
**One render per Generate Preview, always transparent** (`'transparent_alpha'`).
The background is added afterwards by `compose_background()`; both fitz
(alpha=True) and GS (pngalpha) must render with transparency for that to work.
Session state keeps `preview_alpha_bytes` (transparent, ≤1200 px) and
`preview_image_bytes` (what is shown) + `preview_image_bg`; when `bg_type`
changes, the display block re-composes instantly — never re-render the file for
a background change. `preview_download_bytes` is the trimmed full-size PNG.

**Multi-page PDF / AI:** a `Page` selectbox appears in the PDF pre-check block
(before the raster-in-PDF test, so a scanned page 1 can't hide a vector page 2).
`extract_pdf_page()` writes a one-page copy and the whole pipeline (preview,
size, colors, fonts) runs on that copy, so no analyzer needs a page argument.
`result['page_count']` / `['page_number']` are set at the call site. Choosing
another page regenerates automatically (`_page_autogen_attempt` prevents a
failing page from looping). The PDF download is always the whole file.
CorelDRAW is still page 1 only.
The pre-check does not open the PDF on every rerun: page count and the
"is this page just a picture?" answer per page live in
`st.session_state['_pdf_probe']` (`{id, pages, raster{page: bool}}`), and
`_LazyPdf` opens the upload from memory only when an answer is missing.
EPS and SVG have no pages at all: Illustrator saves every artboard into one EPS
image (unless "Use Artboards" is ticked, which writes one file per artboard),
and the artboard list is not readable from the EPS (its XMP says NPages 1; the
rest is in compressed private data). There is nothing to pick for those formats.

### RasterAnalyzer
Reads DPI from Pillow metadata, computes usable print sizes at 300/200 DPI,
verdicts (Production Ready / Marginal / Not Suitable), flags 72 DPI as likely
web graphics, recommends what to request from the customer.
The raster flow analyzes an upload once and keeps the result in
`st.session_state['_raster_analysis']` (`{id, analysis}`); later reruns (method
picker, ArtBot) reuse it. The image itself is always shown from the uploader.

### ColorExtractor — reads color data BEFORE rasterization, never from rendered pixels
**Display rules (critical):**
- Spot colors found → Pantone names ONLY, suppress RGB/CMYK fills
- CMYK doc, no spots → CMYK values, suppress RGB
- Genuinely RGB doc → RGB with red warning badge (RGB is useless in promo production)

**PDF/AI pipeline:** fitz `get_drawings()` → xref scan for `/Separation`
colorspaces → raw byte scan for PANTONE strings → decompressed content-stream
scan for `scn`/`k` operators → CMYK-from-stream overrides xref DeviceRGB artifacts.

**EPS pipeline:** GS `pdfwrite` → fitz content stream → parse `k`/`scn` →
spot names from original EPS text (printable-ASCII filter for binary garbage).
EPS color mode and spot names come from the file's own DSC header via
`_eps_dsc_colors()` (`%%DocumentCustomColors`, `%%DocumentProcessColors`, with
`%%+` continuation lines) when present. Never treat the bare word "Separation"
as a spot color: it is in the boilerplate of every Illustrator EPS, and doing so
labelled black-only files "Spot + CMYK". Files without those comments fall back
to keyword detection (PANTONE names in parentheses).
The pdfwrite conversion comes from `convert_eps_to_pdf()`, which is cached for
the run and shared by color analysis, the font check and the PDF download: an
EPS costs two Ghostscript runs per Generate Preview (one pngalpha preview, one
pdfwrite), not five. Don't add separate `gs` calls for EPS.

RGB EPS files come out of pdfwrite as `r g b rg` fills. When no CMYK or spot
color is found those are listed and the mode is set to RGB (the DSC fallback
would say CMYK, because that word is in Illustrator's boilerplate). More than
24 distinct RGB colors means gradients: the 12 most used are listed with a note.

**Key operators:** Illustrator AI/PDF uses `scn`; GS-converted EPS uses `k`;
plain PostScript uses `setcmykcolor`/`setgray`.

**Pure 100% inks (K100 black, pure C/M/Y):** listed only when actually painted.
`_painted_fill_colors()` walks the content stream (fill color + q/Q stack) and
records the color at each fill/text operator, so colors that are only *set*
(application defaults at the top of the stream) are not listed.
`_skip_stream_color()` always drops registration black (100/100/100/100) and
paper white. Do not go back to dropping every pure ink — a plain black logo
then shows no black and the screen count is one short.

### FontChecker — live text / fonts not outlined
Runs on .pdf/.ai/.eps/.svg after preview generation; result stored in
`result['font_check']` (`live_text`, `fonts[{name, embedded}]`, `sample`) and
shown by `render_font_check()` above Color Analysis; also passed to ArtBot.
- PDF/AI: fitz `get_text("dict")` spans on page 1; `get_fonts()` ext `n/a` = not embedded.
- EPS: GS `pdfwrite` → same PDF check; font names taken from the EPS itself
  (`%%DocumentFonts`, `findfont`) because GS substitutes look-alike fonts.
- SVG: any `<text>` element; names from `font-family`.
Returns None (section hidden) if the file can't be inspected. Page 1 only.

### PdfConverter — vector PDF download for EPS / AI / SVG / CDR
Runs at Generate Preview; bytes in `st.session_state['preview_pdf_bytes']`, facts
in `result['pdf_export']`; shown by `render_pdf_export()` under the PNG download.
**Never build the PDF from the preview PNG or any other image** — that puts a
picture in a PDF wrapper (the mistake an earlier attempt made).
- EPS: GS `pdfwrite -dEPSCrop` (paths, CMYK and `/Separation` spot colors survive).
- AI: the PDF copy inside the file, re-saved with fitz; refuses files saved
  without PDF compatibility.
- SVG: `cairosvg.svg2pdf` (RGB only).
- CDR: `convert_cdr()` (see PreviewGenerator). libcdr outputs RGB only, so Pantone
  and CMYK values are lost and gradients become thin solid bands; the UI says so.
- `_inspect()` counts paths / images / text in the output; the UI says "Vector
  preserved" only when there are no images.

### Decoration Method Check — `decoration_rules.py`
User picks a decoration method (+ imprint location and print width) and gets a
pass / needs-attention / not-suitable verdict with reasons, an "also confirm"
list, and a customer script. Shown in the vector flow (above Font Check) and in
all three raster flows via `render_decoration_check(facts, filename)`.
- `decoration_rules.py` is pure Python (no Streamlit): `METHODS`, `LOCATIONS`,
  `facts_from_vector()`, `facts_from_raster()`, `evaluate()`, `customer_script()`,
  `artbot_summary()`. Change rules there, and update `tests/test_decoration_rules.py`.
- Numbers (max imprint sizes, minimum quantities, 3/16" embroidery text, 1 mm DTFx
  detail, 200/300 dpi) come from Dubow Textile's info sheets and imprint-location
  chart. The UI credits Dubow and tells users to confirm with their own decorator.
  Dubow publishes no screen-print color maximum and no stitch/thread limits, so
  those are shown as information, never as a fail.
- Print area = smaller of method max and location max. Raster dpi is checked at
  the chosen print width (`MIN_DPI` 200, `GOOD_DPI` 300).
- `RasterAnalyzer.analyze()` adds `has_transparency` / `soft_transparency` for the
  no-background and fade warnings. The verdict is also passed to ArtBot.

### ArtBot (sidebar chat)
Senior production artist persona; sees uploaded file context (colors, dims,
warnings) injected into the system prompt. `st.form` for Enter-to-send, key
rotation to clear input, `artbot_pending` → rerun pattern, streaming via
`client.messages.stream()`. Session state: `artbot_history`, `artbot_pending`,
`artbot_input_key`, `bg_type`.

**A question stays in `artbot_pending` until its answer is in the history.**
Streamlit abandons a running script as soon as the user clicks anything else (or
the browser reconnects); the abandoned run's answer is lost. Clearing `pending`
before the API call left the question in the chat with no answer and no error.
`_run_artbot()` therefore tolerates being called again for a question already in
the history. The client has a 60 s timeout; an empty answer becomes a message.
The file context includes `pdf_export` (path and embedded-image counts) so
ArtBot can answer "is this really vector?".

**Chat display:** `artbot_chat_page(history)` builds a self-contained HTML page,
shown with `components.html()`. Answers are Markdown → HTML via `markdown-it-py`
with raw HTML disabled; user text is `html.escape`d. Never paste model or user
text into `st.markdown(..., unsafe_allow_html=True)` — that is how headings came
out as literal `#` and how a `<` could break the box. Test hook:
`ARTBOT_FAKE_REPLY_FILE=<path>` makes ArtBot answer with that file's text
instead of calling the API (used by the automated test; never set in production).

**The sidebar is rendered LAST — do not move it back above the main area.**
`render_artbot_sidebar()` is called before every `st.stop()` (InDesign, GIMP, all
raster flows) and at the end of the script. ArtBot uses `st.rerun()`, and a rerun
discards the state of every widget not yet rendered in that run. When the sidebar
ran first, each ArtBot question made the file uploader forget its file (its X then
cleared nothing) and reset the Decoration Method Check. Any new early `st.stop()`
needs a `render_artbot_sidebar()` call in front of it.

### GIMP (.xcf) — `xcf_tools.py`
Pure Python + Pillow (+ numpy, which Streamlit already installs). `flatten(data)`
returns the RGBA picture GIMP would show plus `layers`, `hidden`, `dpi`, `bits`
and `approximate` (blend modes drawn as Normal; the page lists them).
`flatten_gimp_upload()` in the app turns that into a full-size PNG, a ≤1600 px
display copy and a normal `RasterAnalyzer` result, cached in
`st.session_state['_xcf_flat']`; the page then runs the ordinary raster flow
(print sizes, Decoration Method Check, Mockup Builder, ArtBot context) plus a PNG
download. Unreadable files get the export instructions.
- Do NOT swap in the `gimpformats` package: it peaked near 700 MB on a
  1920 × 1080 file (this reader: about 130 MB) and pulls a newer Pillow.
- Legacy layer modes (< 23) are mixed in gamma space with Pillow. GIMP 2.10 modes
  go through `_linear_draw()`; `_NEW_MODE_SPACES` says, per mode, whether the blend
  and the mix happen in linear light. Those values were found by trying all four
  combinations against GIMP's export; do not "tidy" them.
- A group that is not pass-through is drawn from the picture of itself GIMP saves
  in the file, and its children are skipped. Pass-through groups draw their
  children directly. Top-level layers have no item path in the file.
- `MAX_PIXELS` (24 MP) is a memory limit, about 17 bytes per pixel at peak.
- `tests/data/xcf/*.xcf` were saved by GIMP 2.10.36 from generated shapes
  (`make_samples.scm`), each with the PNG GIMP exported (`*.gimp.png`);
  `tests/test_xcf_tools.py` requires a match. Linear-precision images are exported
  by GIMP as linear PNGs, so the test converts that reference before comparing.
  Also verified by hand on two real projects (5 and 43 layers): max difference 1.

### InDesign (.indd) — `indd_tools.py`
`thumbnail(data)` returns the first-page JPEG from the document's XMP
(`xmpGImg:image`), with the app name and save date. An .indd holds an XMP packet
for every placed image (those have thumbnails too) and several old saves of its
own, so only packets whose CreatorTool is InDesign count, newest first, falling
back when a preview does not decode (long packets are stored in pieces). The
base64 uses `&#xA;` line breaks. Verified by hand on three real documents; CI
uses `make_fixtures.fake_indd()`, which lays packets out the same way.

### Clearing a file
`_clear_file_state()` is the single place that forgets a file. It is used by both
New File buttons and by the uploader's `on_change` callback (the X).

### Mockup Builder
`static/mockup.html` served through `components.html()`; `?mockup=1` route.
Handoff via `@st.cache_resource` dict — single-use tokens, 5-minute expiry.

## Deployment (Railway, Docker)
- `railway.toml`: healthcheck `/_stcore/health` (120s), restart on_failure ×3
- Railway env var `PORT=8501` set manually; domain `www.artcheck.app` → container :8501
- Push to `main` → Railway auto-deploys. **Every push to main goes straight to production.**
- `inject_ga.py` runs at container start: patches Streamlit's index.html with
  branded title + SEO/OG meta tags + GA4 + a 20s health-ping keepalive

### WebSocket stability (do not remove)
Railway's proxy drops idle WebSockets. Three layers:
1. Tornado server-side WS pings
2. Client health ping injected by `inject_ga.py`
3. `start.sh` flags: `enableWebsocketCompression=false`, `fileWatcherType=none`,
   `browser.serverAddress=www.artcheck.app`, `browser.serverPort=443`

### Version pins (do not unpin)
- `streamlit==1.43.2` — 1.55 broke the app
- `pymupdf==1.26.5`, `cairosvg==2.8.2` — later "versions" were phantom/nonexistent on PyPI
- Dockerfile uses runtime libs only (`libcairo2`, `libpangocairo-1.0-0`) —
  `-dev` headers pull ~100 packages and cause boot timeouts

### Memory notes (small instance)
- Keep heavy imports (cairosvg, fitz, pdf2image) lazy — inside methods
- `get_preview_generator()` / `get_color_extractor()` build a fresh object per call
  (they hold no state worth caching)

### Speed notes (measured on a 35,000-path file)
- Content streams of complex art are several MB. Find CMYK operators with
  `ColorExtractor._cmyk_operands()` (operator first, then the four numbers before
  it). A regex of "four numbers then `k`" costs over a second per pass.
- PNGs are saved without `optimize=True` (3x slower for about 1% smaller).
- `generate_preview()` with `'transparent_alpha'` must not call
  `_apply_background()` — that re-encoded the full-size PNG for nothing.
- Count paths with `page.get_cdrawings()`; `get_drawings()` is twice as slow.

## Dev Workflow
```bash
git clone https://github.com/Shernandez520/artcheck.git
git checkout -b <branch>
# edit app_with_embroidery.py  (the production file)
git add <files> && git commit -m "..." && git push -u origin <branch>
# open a pull request; merging it to main deploys immediately
```
Never push straight to `main`. Monitor deploys in the Railway dashboard. Test file uploads (EPS + PDF + PNG)
after every deploy — upload is the core feature.

### Automated browser test (runs on every pull request)
`.github/workflows/tests.yml` builds the production Docker image, starts the app
with a 1 GB memory limit, and runs `tests/e2e_test.py` (Playwright) against it:
PDF, EPS, SVG, DST, PNG, raster-in-PDF, .indd, .xcf, file switching, Mockup Builder
handoff, render cap, Auto background, sizes, multi-page notice, Font Check,
Decoration Method Check, vector PDF export (the downloaded PDF is opened and
checked for paths, images, page size and spot colors). Unit tests run in the same job:
`tests/test_decoration_rules.py` (rules), `tests/test_cdr_tools.py` (CorelDRAW
helper), `tests/test_xcf_tools.py` (GIMP reader against GIMP's own exports) and
`tests/test_indd_tools.py` (InDesign thumbnail). It also fails if temp files are left in
`/tmp` or the container is OOM-killed. Sample files come from
`tests/make_fixtures.py` — no real artwork in the repo (the only binary samples
are the generated-shape GIMP files in `tests/data/xcf`). GA requests are blocked.
- Work on a branch and open a PR; merge only when the check is green.
- When a change intentionally alters something the test asserts (sizes, labels,
  render cap), update `tests/e2e_test.py` in the same PR.
- Run locally: `pip install -r tests/requirements.txt && playwright install chromium`,
  start the app, then `python tests/e2e_test.py --url http://localhost:8501`
  (`SKIP_EPS=1` without Ghostscript). Start the app with
  `ARTBOT_FAKE_REPLY_FILE=tests/fake_artbot_reply.md` for the ArtBot formatting
  check. Not covered: real ArtBot replies from the API.
- CorelDRAW: `tests/test_cdr_tools.py` unit-tests the XHTML → SVG step. There is
  no .cdr in the repo (a CDR can't be generated by code and real artwork must not
  be committed), so the end-to-end CDR path is NOT in CI. It was verified by hand
  with a real 3 MB, 35,000-path CorelDRAW 13 file: 11" × 8.5", vector PDF, no
  images. Re-test with a real .cdr after touching `convert_cdr()`.

## Decoration Method Quick Reference
Matches `decoration_rules.py` (Dubow Textile's published guidelines, used as a
general guide). Keep this table, the ArtBot system prompt and the raster
print-size table in step with that file — the app must not give conflicting numbers.

| Method | File Needs | Key Limits |
|--------|-----------|------------|
| Screen Print | Vector, PMS spot colors | Max 14.5" × 18"; 24-piece minimum; no published color maximum (each color = a screen); gradients print as halftones |
| Embroidery | Any legible art (digitized in-house) or .dst | Max 10" × 10", hats 5" × 2.25"; text at least 3/16" tall; no gradients; no published stitch limit |
| DTFx | Vector or high-res PNG | Max 14" × 18"; detail at least 1 mm (4 pt); no fades or transparency |
| Digital Print (DTG) | Vector, or raster at 200 dpi minimum at print size (300 recommended), RGB preferred | Max 15" × 19"; best on 100% cotton |
| Dye Sublimation | Full color | Max 15" × 19"; white 100% polyester; no white ink |
| Laser Etch | Vector preferred, one color | Max 22" × 11"; tone-on-tone; not for cotton, white, black, heathered or patterned garments |
| Stickers | Full color; custom cut line as PDF | Max 9.8" × 14"; no transparency; 1/8" cut offset |
| Buttons / Magnets | Full color | Max 3" × 3"; type at least 6 pt |
| Hard Goods | Art on the decorator's product template | Per product; decorator's inventory only |

Print resolution everywhere in the app: 200 dpi minimum, 300 dpi recommended.

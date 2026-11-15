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

## Supported File Types
- Vector: .ai, .eps, .pdf, .svg, .cdr, .xcf
- Embroidery: .dst, .pes, .exp, .jef, .vp3, .xxx, .u01
- Raster: .png, .jpg, .jpeg, .gif, .tiff, .bmp, .webp
- Not supported: .indd (user shown export instructions)

## Architecture

### PreviewGenerator
EPS: Ghostscript (`pngalpha`, 300 DPI, `-dEPSCrop`) → fitz fallback.
PDF/AI: fitz (dynamic scale, alpha=True) → pdf2image fallback.
SVG: detect embedded raster → fitz or CairoSVG.
CDR: `convert_cdr()` → `cdr2xhtml` (libcdr) → `cdr_tools.svg_pages_from_libcdr()`
→ CairoSVG PDF → rendered with fitz. cdr2xhtml prints an XHTML page with
`svg:`-prefixed drawings, NOT plain SVG; feeding it straight to CairoSVG fails
("SVG size is undefined") and fitz then lays it out as a tall HTML page. Page 1
only; real page size comes from the converted PDF. One conversion per run is
shared by both preview renders and the PDF download (`_CDR_CONVERSIONS`).
Embroidery: pyembroidery → PIL visualization.
Background via `_apply_background(output_file, bg_type)`; both fitz (alpha=True)
and GS (pngalpha) must render with transparency for backgrounds to work.

### RasterAnalyzer
Reads DPI from Pillow metadata, computes usable print sizes at 300/200 DPI,
verdicts (Production Ready / Marginal / Not Suitable), flags 72 DPI as likely
web graphics, recommends what to request from the customer.

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
- `@st.cache_resource` on `PreviewGenerator`/`ColorExtractor` — do not remove

## Dev Workflow
```bash
git clone https://github.com/Shernandez520/artcheck.git
# edit app_with_embroidery.py  (the production file)
git add <files> && git commit -m "..." && git push   # deploys immediately
```
Monitor deploys in the Railway dashboard. Test file uploads (EPS + PDF + PNG)
after every deploy — upload is the core feature.

### Automated browser test (runs on every pull request)
`.github/workflows/tests.yml` builds the production Docker image, starts the app
with a 1 GB memory limit, and runs `tests/e2e_test.py` (Playwright) against it:
PDF, EPS, SVG, DST, PNG, raster-in-PDF, .indd, file switching, Mockup Builder
handoff, render cap, Auto background, sizes, multi-page notice, Font Check,
Decoration Method Check, vector PDF export (the downloaded PDF is opened and
checked for paths, images, page size and spot colors). `tests/test_decoration_rules.py` unit-tests the rules. It also fails if temp files are left in
`/tmp` or the container is OOM-killed. Sample files come from
`tests/make_fixtures.py` — no real artwork in the repo. GA requests are blocked.
- Work on a branch and open a PR; merge only when the check is green.
- When a change intentionally alters something the test asserts (sizes, labels,
  render cap), update `tests/e2e_test.py` in the same PR.
- Run locally: `pip install -r tests/requirements.txt && playwright install chromium`,
  start the app, then `python tests/e2e_test.py --url http://localhost:8501`
  (`SKIP_EPS=1` without Ghostscript). Not covered: .xcf, live ArtBot replies.
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

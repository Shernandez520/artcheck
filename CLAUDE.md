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
- **PyMuPDF (fitz)** — PDF/AI renderer (dynamic scale to 1200px min, alpha=True for bg support)
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
Embroidery: pyembroidery → PIL visualization.
Background via `_apply_background(output_file, bg_type)`; both fitz (alpha=True)
and GS (pngalpha) must render with transparency for backgrounds to work.

### RasterAnalyzer
Reads DPI from Pillow metadata, computes usable print sizes at 300/200/150 DPI,
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

## Decoration Method Quick Reference
| Method | File Needs | Key Limits |
|--------|-----------|------------|
| Screen Print | Vector, spot colors | 4-6 colors max |
| Embroidery | .dst/.pes or digitizing | Max ~12K stitches left chest |
| DTG | Raster OK, 300 DPI | Best on cotton/light |
| Laser Etch | Vector only | Single color, line art |
| Heat Transfer | Vector, solid colors | Min detail 0.125" |
| Dye Sub | Full color RGB | Polyester only, 300 DPI+ |
| Pad Print | Vector, spot colors | 1-4 colors, small areas |

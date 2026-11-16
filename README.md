# 🎨 ArtCheck

**Instant art file screening for promotional products professionals.**

Upload any vector, embroidery, or image file → get an instant preview, Pantone/CMYK color analysis, a font check, a decoration-method verdict, and a vector PDF to send on. No art department required.

**🔗 Live app: [www.artcheck.app](https://www.artcheck.app)** — free to try, no signup.

![Python](https://img.shields.io/badge/Python-3.11-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-1.43-red) ![Claude](https://img.shields.io/badge/AI-Claude%20Sonnet-orange) ![Deployed](https://img.shields.io/badge/Deployed-Railway-blueviolet)

---

## The Problem

In the promotional products industry, art departments lose hours every day to interruptions that aren't design work:

- "Can you send me a screenshot of this file?"
- "What Pantone is this logo?"
- "Will this work for embroidery?"
- "This file won't open."

Sales reps and CSRs have no self-service option, so every question stops an artist mid-project. After 20+ years in promo production, I built the tool I always wished existed.

## What ArtCheck Does

### Instant Previews
Upload `.ai`, `.eps`, `.pdf`, `.svg`, `.cdr`, or embroidery files (`.dst`, `.pes`, and more) and get a clean PNG preview in seconds — with smart background handling for the classic white-logo-on-white-page problem, and pan/zoom inspection. Backgrounds (auto, light, dark, transparent) switch instantly. The preview panel reports the file's real size in inches (not the size of the preview image), and multi-page PDF and Illustrator files get a page picker so any page or artboard can be previewed and analyzed.

### Real Color Analysis (not pixel guessing)
ArtCheck parses color data from the **file's internal structure before rasterization** — PDF content streams, PostScript operators, separation colorspaces — so it reports what production actually needs:

- Spot colors shown as true Pantone names
- CMYK values (including K% for grayscale work)
- RGB flagged with a warning, because RGB is a red flag in promo production
- Only colors that are actually painted on the page are listed, so an application's unused default black doesn't inflate the count — and a real black logo isn't dropped

### Font Check
Flags live text (fonts that haven't been converted to outlines) in PDF, AI, EPS and SVG files. It lists the fonts used, says which ones aren't embedded, shows the text it found, and gives the rep a ready-to-send request for an outlined file.

### Decoration Method Check
Pick a decoration method (screen print, embroidery, DTF, DTG, dye sublimation, laser etch, stickers, buttons, hard goods), an imprint location and a print width, and get a plain verdict: no problems, needs attention, or not suitable as-is. It checks what the file can show — raster resolution at the actual print size, gradients for embroidery, missing Pantone callouts for screen print, fades for DTF, stitch files that are too big for a hat front — and lists what still has to be confirmed by a person.

The sizes and limits come from [Dubow Textile](https://dubowtextile.com/Info-Sheets)'s published guidelines and are used as a general guide. Every decorator is different, and the app says so on every result.

### Vector PDF Download
EPS, AI, SVG and CorelDRAW files can be downloaded as a PDF that is still vector. The PDF is converted from the file's drawing instructions, never from a preview image, and ArtCheck inspects every PDF it makes: the "vector" label appears only when the result contains no raster images. EPS and AI keep their CMYK values and Pantone spot colors.

### Raster Suitability Check
PNG/JPG uploads get a DPI analysis with usable print sizes at 300 and 200 DPI, a plain-English verdict (Production Ready / Marginal / Not Suitable), and exactly what to ask the customer for instead. Pictures hiding inside a PDF or SVG ("raster saved as vector") are detected and treated as what they are.

### Try It Without a File
No art file handy? **Try a sample logo** on the home page loads a small made-up logo (two Pantone colors, live text) and runs the whole check in one click.

### GIMP and InDesign Files
GIMP (`.xcf`) files are opened directly: ArtCheck flattens the visible layers into one image — layer opacity, masks, groups and the common blend modes included — then runs the same suitability and decoration checks as any other image and offers the result as a PNG. InDesign (`.indd`) files can't be rendered without InDesign, so ArtCheck shows the small page preview InDesign saves inside the file, labelled as a thumbnail, along with what to ask the customer to export.

### ArtBot — AI Production Assistant
A sidebar assistant with a senior-production-artist persona (powered by Claude). It sees your uploaded file's analysis — colors, fonts, size, and the decoration verdict — and answers questions like "what does 'fonts not outlined' mean?" — including word-for-word scripts reps can send to customers.

### Mockup Builder
Drop your trimmed transparent PNG onto any product photo for a quick customer-facing mockup — no design software or SAGE login required.

## Under the Hood

For the technically curious — this is not a thin wrapper around a converter:

- **Rendering pipeline:** PyMuPDF for PDF/AI (dynamic scaling with a pixel cap, alpha-preserving), Ghostscript `pngalpha` for EPS, CairoSVG for SVG, libcdr for CorelDRAW, pyembroidery for stitch files — each with fallbacks
- **Color extraction:** multi-stage pipeline reading `/Separation` colorspace definitions, decompressed content-stream `scn`/`k` operators, and raw PANTONE string scanning; a content-stream walk (fill color plus the graphics-state stack) separates colors that are painted from colors that are merely set; EPS goes through a Ghostscript→PDF→PyMuPDF conversion to reach parseable content streams
- **Vector-preserving conversion:** Ghostscript `pdfwrite` for EPS, the embedded PDF for AI, CairoSVG's PDF surface for SVG, MuPDF's SVG reader for CorelDRAW; every output is re-opened and checked for paths, images and text before it is labelled vector
- **A GIMP reader written for this app:** `xcf_tools.py` parses the XCF format itself (tiles, run-length and zlib compression, 8- to 64-bit samples, layer masks, groups) and mixes layers the way GIMP does — legacy modes in gamma space, GIMP 2.10 modes in linear light — in strips, so memory stays flat. The existing library for this needed about 700 MB for a 1920 × 1080 file; this one uses about 130 MB. It is tested against GIMP's own exports, to within one level per channel
- **Tuned for heavy files:** a 35,000-shape CorelDRAW file went from 15 s to under 8 s by profiling each step (a faster SVG-to-PDF path, operator-anchored scanning of multi-megabyte content streams, no redundant PNG encodes); uploads are analyzed once and not again on every click
- **Rules as data:** decoration rules live in a pure-Python module (`decoration_rules.py`) with no UI dependency, so they are unit-tested on their own
- **Automated tests on every pull request:** GitHub Actions builds the production Docker image, starts the app under a 1 GB memory limit, and drives it in a headless browser — uploading generated PDF, EPS, AI, SVG, GIMP, InDesign, embroidery and raster files, downloading the converted PDFs and inspecting them, and checking the page for each feature. A merge to `main` deploys, so nothing merges without a green run.
- **Production hardening:** Dockerized on Railway, health-checked, WebSocket keepalive layered at three levels (Tornado server pings, client health pings, compression disabled) to survive proxy idle timeouts, memory-conscious lazy imports and resource caching for small-instance stability

**Stack:** Python · Streamlit · PyMuPDF · Ghostscript · CairoSVG · libcdr · pyembroidery · Pillow · Anthropic Claude API · Playwright · GitHub Actions · Docker · Railway

## Supported Files

| Type | Formats |
|------|---------|
| Vector | .ai (PDF-based and PostScript-based), .eps, .pdf, .svg, .cdr |
| Embroidery | .dst, .pes, .exp, .jef, .vp3, .xxx, .u01 |
| Raster | .png, .jpg, .gif, .tiff, .bmp, .webp, .xcf (GIMP, flattened) |
| Thumbnail only | .indd (InDesign) |

## Privacy

Files are processed in memory and discarded immediately. Nothing is stored, and nobody can see your files but you.

## Roadmap

- [x] Vector, embroidery, and raster preview generation
- [x] Spot color / Pantone detection with color-mode verdicts
- [x] Raster print-suitability analysis
- [x] AI production guidance with file awareness (ArtBot)
- [x] Mockup Builder
- [x] Font check (live text / fonts not outlined)
- [x] Decoration method pre-screening with imprint locations and print size
- [x] Vector PDF export for EPS, AI, SVG and CorelDRAW
- [x] Automated browser tests on every pull request
- [x] Page picker for multi-page PDF and Illustrator files
- [x] Instant background switching
- [x] GIMP (.xcf) files opened and flattened; InDesign thumbnails
- [ ] Batch processing
- [ ] Team accounts & file history

## Why ArtCheck Exists

After 20+ years in promotional products production, I was tired of watching talented artists burn out answering the same basic questions over and over. ArtCheck exists so creative teams can finally focus on real design work again.

## Interested?

Currently onboarding early partners. For commercial licensing, API access, or to become an early partner: **artchecksupport@gmail.com** — or open an issue here.

## License

Source-available for portfolio review and learning; commercial use requires a license. See [LICENSE.md](LICENSE.md).

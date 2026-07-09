# 🎨 ArtCheck

**Instant art file screening for promotional products professionals.**

Upload any vector, embroidery, or image file → get an instant preview, Pantone/CMYK color analysis, and production suitability check. No art department required.

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
Upload `.ai`, `.eps`, `.pdf`, `.svg`, `.cdr`, or embroidery files (`.dst`, `.pes`, and more) and get a clean PNG preview in seconds — with smart background handling for the classic white-logo-on-white-page problem, and pan/zoom inspection.

### Real Color Analysis (not pixel guessing)
ArtCheck parses color data from the **file's internal structure before rasterization** — PDF content streams, PostScript operators, separation colorspaces — so it reports what production actually needs:

- Spot colors shown as true Pantone names
- CMYK values (including K% for grayscale work)
- RGB flagged with a warning, because RGB is a red flag in promo production

### Raster Suitability Check
PNG/JPG uploads get a DPI analysis with usable print sizes at 300/200/150 DPI, a plain-English verdict (Production Ready / Marginal / Not Suitable), and exactly what to ask the customer for instead.

### ArtBot — AI Production Assistant
A sidebar assistant with a senior-production-artist persona (powered by Claude). It sees your uploaded file's analysis and answers questions like "what does 'fonts not outlined' mean?" — including word-for-word scripts reps can send to customers.

### Mockup Builder
Drop your trimmed transparent PNG onto any product photo for a quick customer-facing mockup — no design software or SAGE login required.

## Under the Hood

For the technically curious — this is not a thin wrapper around a converter:

- **Rendering pipeline:** PyMuPDF for PDF/AI (dynamic scaling, alpha-preserving), Ghostscript `pngalpha` for EPS, CairoSVG for SVG, pyembroidery for stitch files — each with fallbacks
- **Color extraction:** multi-stage pipeline reading `/Separation` colorspace definitions, decompressed content-stream `scn`/`k` operators, and raw PANTONE string scanning; EPS goes through a Ghostscript→PDF→PyMuPDF conversion to reach parseable content streams
- **Production hardening:** Dockerized on Railway, health-checked, WebSocket keepalive layered at three levels (Tornado server pings, client health pings, compression disabled) to survive proxy idle timeouts, memory-conscious lazy imports and resource caching for small-instance stability

**Stack:** Python · Streamlit · PyMuPDF · Ghostscript · CairoSVG · pyembroidery · Pillow · Anthropic Claude API · Docker · Railway

## Supported Files

| Type | Formats |
|------|---------|
| Vector | .ai, .eps, .pdf, .svg, .cdr, .xcf |
| Embroidery | .dst, .pes, .exp, .jef, .vp3, .xxx, .u01 |
| Raster | .png, .jpg, .gif, .tiff, .bmp, .webp |

## Privacy

Files are processed in memory and discarded immediately. Nothing is stored, and nobody can see your files but you.

## Roadmap

- [x] Vector, embroidery, and raster preview generation
- [x] Spot color / Pantone detection with color-mode verdicts
- [x] Raster print-suitability analysis
- [x] AI production guidance with file awareness (ArtBot)
- [x] Mockup Builder
- [ ] Decoration method pre-screening (embroidery/screen print/laser rules engine)
- [ ] Batch processing
- [ ] Shareable preview links
- [ ] Team accounts & file history

## Why ArtCheck Exists

After 20+ years in promotional products production, I was tired of watching talented artists burn out answering the same basic questions over and over. ArtCheck exists so creative teams can finally focus on real design work again.

## Interested?

Currently onboarding early partners. For commercial licensing, API access, or to become an early partner: **artchecksupport@gmail.com** — or open an issue here.

## License

Source-available for portfolio review and learning; commercial use requires a license. See [LICENSE.md](LICENSE.md).

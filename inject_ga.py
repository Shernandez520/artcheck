#!/usr/bin/env python3
"""
Patch Streamlit's index.html at container startup:
  1. Replace the generic <title>Streamlit</title> with ArtCheck branding
  2. Inject SEO + social sharing meta tags (description, Open Graph, Twitter)
     so shared links on LinkedIn/Facebook show ArtCheck, not "Streamlit"
  3. Inject GA4 analytics tag
  4. Inject WebSocket keepalive health ping (Railway proxy drops idle connections)
Run this before launching Streamlit (see start.sh).
"""
import glob

GA_ID = "G-E1711T2D9R"

SITE_URL = "https://www.artcheck.app"
SITE_TITLE = "ArtCheck — Instant Art File Checker for Promotional Products"
SITE_DESCRIPTION = (
    "Upload any vector, embroidery, or image file and get an instant preview, "
    "Pantone/CMYK color analysis, and production suitability check. "
    "Built for promo industry sales reps and CSRs — no art department needed."
)

HEAD_SNIPPET = f"""
    <!-- SEO / social sharing -->
    <meta name="description" content="{SITE_DESCRIPTION}">
    <link rel="canonical" href="{SITE_URL}/">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{SITE_URL}/">
    <meta property="og:site_name" content="ArtCheck">
    <meta property="og:title" content="{SITE_TITLE}">
    <meta property="og:description" content="{SITE_DESCRIPTION}">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="{SITE_TITLE}">
    <meta name="twitter:description" content="{SITE_DESCRIPTION}">
    <!-- Google tag (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', '{GA_ID}');
    </script>
    <!-- ArtCheck event bridge: Streamlit components render in iframes and cannot
         reach gtag directly, so they postMessage up to the parent page. -->
    <script>
      window.addEventListener('message', function(e) {{
        try {{
          var d = e.data;
          if (!d || d.type !== 'artcheck_event' || typeof d.name !== 'string') return;
          if (typeof gtag !== 'function') return;
          gtag('event', d.name, d.params || {{}});
        }} catch (err) {{}}
      }});
    </script>
    <!-- HTTP health ping: belt-and-suspenders keepalive alongside Tornado WS pings -->
    <script>
      (function() {{
        setInterval(function() {{
          fetch('/_stcore/health').catch(function(){{}});
        }}, 20000);
      }})();
    </script>
"""


def find_index_html():
    patterns = [
        "/usr/local/lib/python*/dist-packages/streamlit/static/index.html",
        "/usr/local/lib/python*/site-packages/streamlit/static/index.html",
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


def inject():
    path = find_index_html()
    if not path:
        print("inject: Could not find Streamlit index.html")
        return

    with open(path, "r") as f:
        content = f.read()

    # 1. Branded title (crawlers and link unfurlers read the raw HTML,
    #    they never see the title Streamlit sets later via JavaScript)
    if "<title>Streamlit</title>" in content:
        content = content.replace(
            "<title>Streamlit</title>", f"<title>{SITE_TITLE}</title>", 1
        )
        print("inject: Title replaced")

    # 2-4. Meta tags + GA + keepalive
    if GA_ID in content:
        print(f"inject: Head snippet already present in {path}")
    else:
        content = content.replace("</head>", f"{HEAD_SNIPPET}</head>", 1)
        print(f"inject: Head snippet injected into {path}")

    with open(path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    inject()

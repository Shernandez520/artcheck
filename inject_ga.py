#!/usr/bin/env python3
"""
Inject GA4 tag into Streamlit's index.html at container startup.
Run this before launching Streamlit.
"""
import os
import glob

GA_ID = "G-E1711T2D9R"

GA_SCRIPT = f"""
    <!-- Google tag (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', '{GA_ID}');
    </script>
    <!-- WebSocket keepalive: prevents Railway proxy from dropping idle connections -->
    <script>
      (function() {{
        var _stWs = null;
        var _origWS = window.WebSocket;

        // Intercept WebSocket constructor to capture Streamlit's stream connection
        function WSProxy(url, protocols) {{
          var ws = protocols ? new _origWS(url, protocols) : new _origWS(url);
          if (url && url.indexOf('_stcore') > -1) {{
            _stWs = ws;
          }}
          return ws;
        }}
        WSProxy.prototype = _origWS.prototype;
        WSProxy.CONNECTING = _origWS.CONNECTING;
        WSProxy.OPEN = _origWS.OPEN;
        WSProxy.CLOSING = _origWS.CLOSING;
        WSProxy.CLOSED = _origWS.CLOSED;
        window.WebSocket = WSProxy;

        setInterval(function() {{
          // Send an empty binary frame through the WebSocket — this is what
          // Railway's proxy actually monitors. An empty protobuf BackMsg is a no-op.
          if (_stWs && _stWs.readyState === 1) {{
            try {{ _stWs.send(new ArrayBuffer(0)); }} catch(e) {{}}
          }}
          // Also HTTP ping as belt-and-suspenders
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
        print("GA4: Could not find Streamlit index.html")
        return

    with open(path, 'r') as f:
        content = f.read()

    if GA_ID in content:
        print(f"GA4: Already injected into {path}")
        return

    content = content.replace('</head>', f'{GA_SCRIPT}</head>', 1)

    with open(path, 'w') as f:
        f.write(content)

    print(f"GA4: Successfully injected into {path}")

if __name__ == "__main__":
    inject()

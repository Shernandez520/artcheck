"""Unit test for ws_keepalive.py: the WebSocket ping patch is applied exactly once.

    python tests/test_ws_keepalive.py

Applying it on every Streamlit run (as the app once did) chained one wrapper per
run and kept every run's variables alive: the server's memory grew by tens of
megabytes per preview until it was killed.
"""
import asyncio
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import tornado.websocket  # noqa: E402

PASSED = 0


def check(name, condition, detail=""):
    global PASSED
    if not condition:
        print(f"❌ {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✅ {name}")


untouched = tornado.websocket.WebSocketHandler.get
import ws_keepalive  # noqa: E402

first = tornado.websocket.WebSocketHandler.get
check("the handler is wrapped on import", first is not untouched and tornado.websocket.WebSocketHandler._artcheck_ping_patch)

for _ in range(50):          # what 50 Streamlit reruns used to do
    importlib.reload(ws_keepalive)
    ws_keepalive._install()
check("applying it again does not wrap the wrapper", tornado.websocket.WebSocketHandler.get is first)


class _App:
    settings = {}


class _FakeHandler:
    application = _App()


try:
    asyncio.run(first(_FakeHandler()))
except Exception:
    pass                     # the real Tornado handler cannot run on a stand-in; the settings are set before it
check("a new connection gets ping settings",
      _App.settings.get("websocket_ping_interval") == 20 and _App.settings.get("websocket_ping_timeout") == 60,
      str(_App.settings))

with open(os.path.join(HERE, "..", "app_with_embroidery.py"), encoding="utf-8") as fh:
    app_source = fh.read()
check("the app file does not patch the handler itself (it is re-run on every click)",
      "WebSocketHandler.get =" not in app_source and "import ws_keepalive" in app_source)

print(f"\n{PASSED} checks passed")

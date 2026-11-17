"""Server-side WebSocket pings for Streamlit's Tornado server.

Railway's proxy closes connections it thinks are idle. Tornado can send pings,
but Streamlit does not turn them on, so the handler is wrapped to set the ping
interval when a connection opens.

THIS MUST LIVE IN ITS OWN MODULE AND RUN ONCE PER PROCESS. It used to sit at the
top of app_with_embroidery.py, and Streamlit runs that file again on every
click. Each run wrapped the previous wrapper, so:
- every run's variables (full-size preview images included) stayed referenced
  by the chain for as long as the server lived: about 80 MB per large preview,
  never freed, until the container ran out of memory;
- every new connection had to pass through one more wrapper per run.
A module is imported once, so `import ws_keepalive` is safe to repeat.
"""
import tornado.websocket as _tws

PING_INTERVAL_SECONDS = 20
PING_TIMEOUT_SECONDS = 60


def _install():
    handler = _tws.WebSocketHandler
    if getattr(handler, "_artcheck_ping_patch", False):
        return
    original_get = handler.get

    async def get_with_ping(self, *args, **kwargs):
        self.application.settings.setdefault("websocket_ping_interval", PING_INTERVAL_SECONDS)
        self.application.settings.setdefault("websocket_ping_timeout", PING_TIMEOUT_SECONDS)
        return await original_get(self, *args, **kwargs)

    handler.get = get_with_ping
    handler._artcheck_ping_patch = True


try:
    _install()
except Exception:
    pass

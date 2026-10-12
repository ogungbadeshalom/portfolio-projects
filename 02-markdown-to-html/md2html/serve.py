"""Local preview server for rendered Markdown documents.

Two backends are provided:

* **FastAPI + uvicorn** when available -- each input file is rendered to a
  standalone HTML string and served at ``/file/{name}`` with an index page.
* **stdlib ``http.server``** otherwise -- a plain HTTP handler that embeds the
  rendered document and returns it for any path. This keeps ``--serve`` working
  in a minimal environment.

``create_app()`` and ``run_server()`` are the public entry points.
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

from .converter import convert

try:
    from fastapi import FastAPI

    _FASTAPI_LOADED = True
    try:
        import uvicorn  # noqa: F401

        _UVICORN_LOADED = True
    except ImportError:
        _UVICORN_LOADED = False
except ImportError:  # pragma: no cover
    _FASTAPI_LOADED = False
    _UVICORN_LOADED = False
    FastAPI = None  # type: ignore[assignment]

__all__ = ["create_app", "run_server", "servers"]


def render_sources(sources: List[Path], theme: str) -> Dict[str, str]:
    """Render every Markdown file to ``{display_name: html}``.

    Args:
        sources: Paths to Markdown files to render.
        theme: CSS theme name passed through to :func:`convert`.

    Returns:
        Ordered mapping of each file's name (no extension) to its HTML.
    """
    rendered: Dict[str, str] = {}
    for src in sources:
        text = src.read_text(encoding="utf-8")
        rendered[src.stem] = convert(text, theme=theme)
    return rendered


def _index_page(rendered: Dict[str, str]) -> str:
    links = "".join(
        f'<li><a href="/file/{name}">{name}.md</a></li>' for name in rendered
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>md2html preview</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 640px; margin: 3rem auto; }}
a {{ color: #0969da; text-decoration: none; }}
</style></head>
<body><h1>md2html preview</h1>
<p>Choose a rendered document:</p><ul>{links}</ul></body></html>"""


def create_app(sources: List[Path], theme: str) -> object:
    """Build a FastAPI application (or a stdlib fallback handler).

    Args:
        sources: Markdown files to render.
        theme: Theme passed to :func:`convert`.

    Returns:
        A FastAPI ``app`` when FastAPI is importable, otherwise a tuple
        ``(handler_cls, rendered)`` usable by :func:`httpd_serve`.
    """
    rendered = render_sources(sources, theme)
    if _FASTAPI_LOADED:
        app: FastAPI = FastAPI(title="md2html preview")

        @app.get("/")
        def index() -> str:
            return _index_page(rendered)

        @app.get("/file/{name}")
        def file_page(name: str) -> str:
            if name not in rendered:
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Not found")
            return rendered[name]

        return app
    return _stdlib_handler(rendered)


# --------------------------------------------------------------------------- #
# stdlib fallback
# --------------------------------------------------------------------------- #
def _stdlib_handler(rendered: Dict[str, str]):
    """Build an ``http.server.BaseHTTPRequestHandler`` subclass serving ``rendered``."""

    from http.server import BaseHTTPRequestHandler

    class _Handler(BaseHTTPRequestHandler):
        _rendered = rendered

        def _send(self, body: bytes, ctype: str = "text/html; charset=utf-8") -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            name = self.path.rstrip("/").split("/")[-1]
            if self.path in ("/", "/index.html"):
                self._send(_index_page(self._rendered).encode("utf-8"))
            elif name and name in self._rendered:
                self._send(self._rendered[name].encode("utf-8"))
            else:
                self.send_error(404, "Not found")

        def log_message(self, fmt: str, *args: object) -> None:  # quiet logs
            pass

    return _Handler


def httpd_serve(rendered: Dict[str, str], host: str, port: int) -> None:
    """Serve ``rendered`` over stdlib ``http.server``."""

    import http.server

    handler = _stdlib_handler(rendered)
    with http.server.ThreadingHTTPServer((host, port), handler) as httpd:
        _announce(host, port)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def run_server(
    sources: List[Path],
    theme: str,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    """Render ``sources`` and run a blocking preview server on ``host:port``.

    Args:
        sources: Markdown files to render and serve.
        theme: Theme passed to :func:`convert`.
        host: Bind address for the server.
        port: TCP port to bind.
        open_browser: Open the default browser against the index page.
    """
    imported_create = create_app(sources, theme)
    if _FASTAPI_LOADED and _UVICORN_LOADED:
        import uvicorn

        if open_browser:
            _open_later(host, port)
        uvicorn.run(imported_create, host=host, port=port, log_level="warning")
    elif not isinstance(imported_create, dict) and _FASTAPI_LOADED:
        # FastAPI present but uvicorn missing: fall back to stdlib.
        rendered = {(p.stem): convert(p.read_text(encoding="utf-8"), theme=theme) for p in sources}
        httpd_serve(rendered, host, port)
    else:
        # stdlib fallback handler was returned.
        rendered = {
            p.stem: convert(p.read_text(encoding="utf-8"), theme=theme) for p in sources
        }
        httpd_serve(rendered, host, port)


def _open_later(host: str, port: int) -> None:
    """Open the browser a moment after the server starts listening."""

    def _open() -> None:
        webbrowser.open(f"http://{host}:{port}/")

    threading.Timer(0.5, _open).start()


def _announce(host: str, port: int) -> None:
    print(f"Serving render at http://{host}:{port}/  (Ctrl+C to stop)")


servers = {
    "fastapi": _FASTAPI_LOADED and _UVICORN_LOADED,
    "uvicorn": _UVICORN_LOADED,
}
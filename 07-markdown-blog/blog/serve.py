"""Local preview server for a built blog.

:class:`BlogHTTPServer` serves the ``dist/`` folder from a given root over
Python's stdlib ``http.server``.  It adds two conveniences:

* **Draft mode** -- ``--drafts`` re-builds including draft posts so an author
  can preview them without publishing.
* **Live rebuild** -- a lightweight watcher polls the ``posts/`` and
  ``static/`` trees and re-runs the build whenever they change.  (This is the
  optional "auto-rebuild" stretch; purely stdlib, no watchdog dependency.)
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple

from . import builder


class NoCacheHandler(SimpleHTTPRequestHandler):
    """Request handler that disables HTTP caching for previews.

    Attributes
    ----------
    directory:
        Set by the server to the ``dist/`` path before the handler is used.
    """

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


class BlogHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server rooted at the blog's ``dist/`` directory."""

    def __init__(
        self,
        server_address: Tuple[str, int],
        root: Path,
        include_drafts: bool = False,
        rebuild_on_change: bool = False,
    ) -> None:
        self.root = root
        self.include_drafts = include_drafts
        self.rebuild_on_change = rebuild_on_change
        dist_dir = root / "dist"
        if not dist_dir.exists():
            builder.build(root, include_drafts=include_drafts, quiet=False)

        class Handler(NoCacheHandler):  # noqa: N806 - name is required by handler API
            def __init__(self, *args, directory=dist_dir, **kwargs):
                super().__init__(*args, directory=str(directory), **kwargs)

        super().__init__(server_address, Handler)
        if rebuild_on_change:
            self._watcher_stop = threading.Event()
            self._watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
            self._watcher_thread.start()

    def _watch_loop(self) -> None:
        """Poll for content changes and rebuild when they happen."""
        last_sig = self._tree_signature()
        while not self._watcher_stop.is_set():
            time.sleep(1.2)
            sig = self._tree_signature()
            if sig != last_sig:
                last_sig = sig
                try:
                    builder.build(self.root, include_drafts=self.include_drafts, quiet=False)
                except Exception as exc:  # noqa: BLE001 - keep serving on failure
                    print(f"[serve] rebuild failed: {exc}")

    def _tree_signature(self) -> Tuple[float, int, list]:
        posts = list((self.root / "posts").glob("*.md"))
        static = []
        st = self.root / "static"
        if st.is_dir():
            static = [p for p in st.rglob("*") if p.is_file()]
        files = posts + static
        mtime = max([p.stat().st_mtime for p in files], default=0.0)
        return (mtime, len(files), sorted([p.name for p in files]))

    def shutdown(self) -> None:
        if self.rebuild_on_change:
            self._watcher_stop.set()
            if self._watcher_thread is not None and self._watcher_thread.is_alive():
                self._watcher_thread.join(timeout=2)
        super().shutdown()


def make_server(host: str, port: int, root: Path, include_drafts: bool, rebuild_on_change: bool) -> BlogHTTPServer:
    """Create and bind a :class:`BlogHTTPServer`."""
    server = BlogHTTPServer(
        (host, port),
        root=root,
        include_drafts=include_drafts,
        rebuild_on_change=rebuild_on_change,
    )
    return server


def url_for(server: BlogHTTPServer) -> str:
    host, port = server.server_address
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return f"http://{display_host}:{port}/"
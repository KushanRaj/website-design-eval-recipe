from __future__ import annotations

import os
import threading
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

ServeMode = Literal["static", "spa"]


def normalize_serve_mode(value: str | None) -> ServeMode:
    if value in (None, "", "static"):
        return "static"
    if value == "spa":
        return "spa"
    raise ValueError(f"Unknown serve mode: {value}")


class _QuietHandler(SimpleHTTPRequestHandler):
    serve_mode: ServeMode = "static"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def send_head(self):  # type: ignore[no-untyped-def]
        if self.serve_mode == "spa" and self._should_spa_fallback():
            translated = self.translate_path(self.path)
            if not os.path.exists(translated):
                original_path = self.path
                self.path = "/index.html"
                try:
                    return super().send_head()
                finally:
                    self.path = original_path
        return super().send_head()

    def _should_spa_fallback(self) -> bool:
        if self.command not in {"GET", "HEAD"}:
            return False
        parsed = urlparse(self.path)
        first_segment = parsed.path.strip("/").split("/", 1)[0].lower()
        if first_segment in {"assets", "css", "fonts", "font", "images", "img", "js", "media", "static"}:
            return False
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {"", ".html"}:
            return False
        accept = self.headers.get("Accept", "")
        return "text/html" in accept


@dataclass
class StaticServer:
    root: Path
    httpd: ThreadingHTTPServer
    thread: threading.Thread
    base_url: str
    serve_mode: ServeMode = "static"

    @classmethod
    def start(cls, root: Path, *, serve_mode: str | None = "static") -> "StaticServer":
        root = root.resolve()
        normalized_mode = normalize_serve_mode(serve_mode)
        handler_cls = type(
            f"WdeStaticHandler_{normalized_mode}",
            (_QuietHandler,),
            {"serve_mode": normalized_mode},
        )
        handler = partial(handler_cls, directory=str(root))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        host, port = httpd.server_address[:2]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return cls(
            root=root,
            httpd=httpd,
            thread=thread,
            base_url=f"http://{host}:{port}",
            serve_mode=normalized_mode,
        )

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        with suppress(RuntimeError):
            self.thread.join(timeout=2)

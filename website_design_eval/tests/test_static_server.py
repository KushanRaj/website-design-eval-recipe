from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from website_design_eval.static_server import StaticServer


def _fetch(url: str, *, accept: str = "text/html") -> tuple[int, str]:
    request = Request(url, headers={"Accept": accept})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


class StaticServerTests(unittest.TestCase):
    def test_spa_fallback_serves_index_for_page_navigation_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "index.html").write_text("<main>SPA shell</main>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")

            server = StaticServer.start(root, serve_mode="spa")
            try:
                status, body = _fetch(f"{server.base_url}/minerals")
                self.assertEqual(status, 200)
                self.assertIn("SPA shell", body)

                status, body = _fetch(f"{server.base_url}/minerals.html")
                self.assertEqual(status, 200)
                self.assertIn("SPA shell", body)

                status, body = _fetch(f"{server.base_url}/assets/app.js", accept="*/*")
                self.assertEqual(status, 200)
                self.assertIn("console.log", body)

                status, _body = _fetch(f"{server.base_url}/assets/missing.js", accept="text/html")
                self.assertEqual(status, 404)
            finally:
                server.close()

    def test_static_mode_does_not_spa_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "index.html").write_text("<main>Static home</main>", encoding="utf-8")

            server = StaticServer.start(root, serve_mode="static")
            try:
                status, _body = _fetch(f"{server.base_url}/minerals")
                self.assertEqual(status, 404)
            finally:
                server.close()


if __name__ == "__main__":
    unittest.main()

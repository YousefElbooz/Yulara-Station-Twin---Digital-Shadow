"""
Training tab server: serves the page and the training progress file, nothing else
(so .env and the data folder are never exposed).

Usage (from the project folder)
  .venv\\Scripts\\python tools\\training_monitor\\serve.py        # http://localhost:8765
"""
import http.server
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = Path(__file__).with_name("index.html")
PROGRESS = ROOT / "data/training/progress.json"
PORT = 8765


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/progress.json":
            if PROGRESS.exists():
                for _ in range(5):
                    try:
                        self._send(200, PROGRESS.read_bytes(), "application/json")
                        break
                    except PermissionError:
                        import time
                        time.sleep(0.02)
            else:
                self._send(404, b'{"status":"not_started"}', "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"training tab on http://localhost:{PORT}")
        httpd.serve_forever()

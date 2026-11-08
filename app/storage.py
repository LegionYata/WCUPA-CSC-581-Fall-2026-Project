"""storage service: simple object store over an emptyDir volume.
"""
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import log, quiet_health_logs, read_body, send  # noqa: E402

DATA = os.environ.get("DATA_DIR", "/data")
PORT = int(os.environ.get("PORT", "8083"))
SAFE = re.compile(r"^(raw|processed|results)/[A-Za-z0-9._-]+$")


@quiet_health_logs
class Handler(BaseHTTPRequestHandler):
    def _file(self):
        p = self.path.split("?")[0]
        if not p.startswith("/objects/"):
            return None
        rel = p[len("/objects/"):]
        return os.path.join(DATA, rel) if SAFE.match(rel) else None

    def do_GET(self):
        if self.path == "/healthz":
            return send(self, 200, "ok", "text/plain")
        if self.path == "/stats":
            stats = {d: len(os.listdir(os.path.join(DATA, d))) if os.path.isdir(os.path.join(DATA, d)) else 0
                     for d in ("raw", "processed", "results")}
            return send(self, 200, stats)
        f = self._file()
        if not f:
            return send(self, 400, {"error": "invalid object path"})
        if not os.path.exists(f):
            return send(self, 404, {"error": "not found"})
        with open(f, "rb") as fh:
            send(self, 200, fh.read(), "application/octet-stream")

    def do_PUT(self):
        f = self._file()
        if not f:
            return send(self, 400, {"error": "invalid object path"})
        body = read_body(self)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        tmp = f + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(body)
        os.replace(tmp, f)  # atomic: readers never see half-written files
        send(self, 201, {"stored": os.path.relpath(f, DATA), "bytes": len(body)})


if __name__ == "__main__":
    for d in ("raw", "processed", "results"):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)
    log(f"storage listening on :{PORT}, data dir {DATA}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

"""preprocessor: fetches the raw image from storage, prepares the model input, stores it,
then invokes inference over HTTP.
"""
import hashlib
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import POD, UUID_RE, http, log, post_json, quiet_health_logs, read_body, send  # noqa: E402

PORT = int(os.environ.get("PORT", "8081"))
STORAGE = os.environ.get("STORAGE_URL", "http://storage-svc:8083")
INFERENCE = os.environ.get("INFERENCE_URL", "http://inference-svc:8082")
SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def image_info(b):
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
    if b[:3] == b"\xff\xd8\xff":
        i = 2
        while i < len(b) - 9:
            if b[i] != 0xFF:
                i += 1
                continue
            m = b[i + 1]
            if m == 0xFF:
                i += 1
            elif m in SOF:
                return "jpeg", int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
            elif m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                i += 2
            else:
                i += 2 + int.from_bytes(b[i + 2:i + 4], "big")
    return "unknown", None, None


@quiet_health_logs
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            return send(self, 200, "ok", "text/plain")
        send(self, 404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/preprocess":
            return send(self, 404, {"error": "not found"})
        try:
            image_id = json.loads(read_body(self) or b"{}").get("id", "")
        except ValueError:
            return send(self, 400, {"error": "invalid JSON"})
        if not UUID_RE.match(image_id):
            return send(self, 400, {"error": "id must be a UUIDv4"})
        start = time.time()
        try:
            status, raw = http("GET", f"{STORAGE}/objects/raw/{image_id}")
            if status != 200:
                return send(self, 404, {"error": f"raw image not found (storage returned {status})"})
            fmt, w, h = image_info(raw)
            tensor = {
                "id": image_id,
                "source": {"format": fmt, "width": w, "height": h, "bytes": len(raw),
                           "sha256": hashlib.sha256(raw).hexdigest()},
                "target_shape": [300, 300, 3],
                "normalization": {"mean": 127.5, "scale": 1 / 127.5},
                "preprocessed_by": POD,
            }
            http("PUT", f"{STORAGE}/objects/processed/{image_id}.json", json.dumps(tensor).encode())
            log(f"preprocessed {image_id}: {fmt} {w}x{h} in {(time.time() - start) * 1000:.1f} ms -> invoking inference")
            status, body = post_json(f"{INFERENCE}/infer", {"id": image_id}, timeout=30)
            return send(self, status, body)
        except Exception as e:
            log(f"preprocess {image_id} failed: {e}")
            return send(self, 502, {"error": str(e)})


if __name__ == "__main__":
    log(f"preprocessor listening on :{PORT} (storage={STORAGE}, inference={INFERENCE})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

"""upload-api: the only externally exposed service (NodePort 30080).

  POST /images              upload an image (multipart field "image", or raw body)
                            -> 202 Accepted {"id": <uuid4>, ...}
  GET  /images/<id>/result  -> 200 with detection JSON, 202 while processing,
                               404 unknown id, 500 if the pipeline failed
  GET  /healthz             probe endpoint
"""
import json
import os
import sys
import threading
import uuid
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import UUID_RE, http, log, post_json, quiet_health_logs, read_body, send  # noqa: E402

PORT = int(os.environ.get("PORT", "8080"))
STORAGE = os.environ.get("STORAGE_URL", "http://storage-svc:8083")
PREPROCESSOR = os.environ.get("PREPROCESSOR_URL", "http://preprocessor-svc:8081")
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))


def extract_image(ctype, body):
    """Return image bytes from a multipart/form-data or raw upload."""
    if ctype.startswith("multipart/form-data"):
        msg = BytesParser(policy=email_policy).parsebytes(
            b"MIME-Version: 1.0\r\nContent-Type: " + ctype.encode() + b"\r\n\r\n" + body)
        for part in msg.iter_parts():
            if part.get_param("name", header="content-disposition") == "image" or part.get_filename():
                return part.get_payload(decode=True) or b""
        return b""
    return body


def is_image(b):
    return b[:3] == b"\xff\xd8\xff" or b[:8] == b"\x89PNG\r\n\x1a\n"


def run_pipeline(image_id):
    """Runs in a background thread so the client gets 202 immediately."""
    try:
        status, body = post_json(f"{PREPROCESSOR}/preprocess", {"id": image_id}, timeout=60)
        log(f"pipeline for {image_id} finished: preprocessor returned {status}")
        if status >= 400:
            raise RuntimeError(f"preprocessor returned {status}: {body[:200]!r}")
    except Exception as e:
        log(f"pipeline for {image_id} FAILED: {e}")
        err = json.dumps({"id": image_id, "status": "failed", "error": str(e)}).encode()
        try:
            http("PUT", f"{STORAGE}/objects/results/{image_id}.error.json", err)
        except Exception as e2:
            log(f"could not record error for {image_id}: {e2}")


@quiet_health_logs
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            return send(self, 200, "ok", "text/plain")
        parts = self.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "images" and parts[2] == "result":
            image_id = parts[1]
            if not UUID_RE.match(image_id):
                return send(self, 400, {"error": "id must be a UUIDv4"})
            status, body = http("GET", f"{STORAGE}/objects/results/{image_id}.json")
            if status == 200:
                return send(self, 200, body)
            status, body = http("GET", f"{STORAGE}/objects/results/{image_id}.error.json")
            if status == 200:
                return send(self, 500, body)
            status, _ = http("GET", f"{STORAGE}/objects/raw/{image_id}")
            if status == 200:
                return send(self, 202, {"id": image_id, "status": "processing"})
            return send(self, 404, {"error": "unknown id"})
        send(self, 404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/images":
            return send(self, 404, {"error": "not found"})
        body = read_body(self)
        if len(body) > MAX_BYTES:
            return send(self, 413, {"error": f"upload larger than {MAX_BYTES} bytes"})
        image = extract_image(self.headers.get("Content-Type", ""), body)
        if not image or not is_image(image):
            return send(self, 400, {"error": "upload a JPEG or PNG (multipart field 'image' or raw body)"})
        image_id = str(uuid.uuid4())
        try:
            status, _ = http("PUT", f"{STORAGE}/objects/raw/{image_id}", image)
            if status >= 400:
                raise RuntimeError(f"storage returned {status}")
        except Exception as e:
            log(f"could not store {image_id}: {e}")
            return send(self, 503, {"error": "storage unavailable", "detail": str(e)})
        log(f"accepted {image_id} ({len(image)} bytes), invoking preprocessor")
        threading.Thread(target=run_pipeline, args=(image_id,), daemon=True).start()
        send(self, 202, {"id": image_id, "status": "accepted", "result_url": f"/images/{image_id}/result"})


if __name__ == "__main__":
    log(f"upload-api listening on :{PORT} (storage={STORAGE}, preprocessor={PREPROCESSOR})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

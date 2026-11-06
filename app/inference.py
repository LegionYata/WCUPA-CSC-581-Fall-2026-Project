"""inference: fetches the processed input from storage, runs detection, stores result JSON.
Every request is appended to /var/log/app/access.log, which the access-logger sidecar streams.

Milestone 2 note: detection is a placeholder (empty detections list) so the service wiring,
scaling and self-healing can be demonstrated. MobileNet-SSD (CPU, threshold >= 0.5) is planned
for Milestone 3. "served_by" shows which of the 3 replicas handled the request.

  POST /infer {"id": "<uuid>"}
  GET  /healthz
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import POD, UUID_RE, http, log, quiet_health_logs, read_body, send  # noqa: E402

PORT = int(os.environ.get("PORT", "8082"))
STORAGE = os.environ.get("STORAGE_URL", "http://storage-svc:8083")
ACCESS_LOG = os.environ.get("ACCESS_LOG", "/var/log/app/access.log")
THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.5"))


def access_log(image_id, status, latency_ms):
    line = (f"{time.strftime('%Y-%m-%dT%H:%M:%S')} pod={POD} method=POST path=/infer "
            f"id={image_id} status={status} latency_ms={latency_ms:.1f}\n")
    try:
        with open(ACCESS_LOG, "a") as fh:
            fh.write(line)
    except OSError as e:
        log(f"cannot write access log: {e}")


@quiet_health_logs
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            return send(self, 200, "ok", "text/plain")
        send(self, 404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/infer":
            return send(self, 404, {"error": "not found"})
        start = time.time()
        image_id = ""
        try:
            image_id = json.loads(read_body(self) or b"{}").get("id", "")
            if not UUID_RE.match(image_id):
                access_log(image_id, 400, 0)
                return send(self, 400, {"error": "id must be a UUIDv4"})
            status, body = http("GET", f"{STORAGE}/objects/processed/{image_id}.json")
            if status != 200:
                access_log(image_id, 404, (time.time() - start) * 1000)
                return send(self, 404, {"error": "processed input not found"})
            tensor = json.loads(body)
            latency = (time.time() - start) * 1000
            result = {
                "id": image_id,
                "status": "completed",
                "model": "placeholder (MobileNet-SSD planned for Milestone 3)",
                "confidence_threshold": THRESHOLD,
                "detections": [],
                "input": tensor.get("source"),
                "preprocessed_by": tensor.get("preprocessed_by"),
                "served_by": POD,
                "inference_latency_ms": round(latency, 1),
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            http("PUT", f"{STORAGE}/objects/results/{image_id}.json", json.dumps(result).encode())
            access_log(image_id, 200, latency)
            log(f"inference done for {image_id} in {latency:.1f} ms")
            send(self, 200, result)
        except Exception as e:
            access_log(image_id, 500, (time.time() - start) * 1000)
            log(f"inference {image_id} failed: {e}")
            send(self, 500, {"error": str(e)})


if __name__ == "__main__":
    os.makedirs(os.path.dirname(ACCESS_LOG), exist_ok=True)
    log(f"inference listening on :{PORT} (storage={STORAGE})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

SERVICE = os.environ.get("SERVICE_NAME", "service")
POD = os.environ.get("HOSTNAME", "unknown-pod")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def log(msg):
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] [{SERVICE}] [{POD}] {msg}", flush=True)


def http(method, url, data=None, headers=None, timeout=10, retries=3):
    """HTTP call with timeout and exponential-backoff retries.
    Returns (status, body). 4xx responses are returned, not retried."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return e.code, e.read()
            last = f"HTTP {e.code}"
        except Exception as e:  # connection refused, DNS failure, timeout...
            last = repr(e)
        log(f"retry {attempt}/{retries} for {method} {url}: {last}")
        time.sleep(0.5 * (2 ** (attempt - 1)))
    raise RuntimeError(f"{method} {url} failed after {retries} attempts: {last}")


def post_json(url, obj, timeout=30):
    return http("POST", url, json.dumps(obj).encode(), {"Content-Type": "application/json"}, timeout=timeout)


def send(handler, code, body, ctype="application/json"):
    if isinstance(body, (dict, list)):
        body = json.dumps(body, indent=2).encode()
    elif isinstance(body, str):
        body = body.encode()
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler):
    n = int(handler.headers.get("Content-Length", 0) or 0)
    return handler.rfile.read(n) if n > 0 else b""


def quiet_health_logs(handler_cls):
    """Suppress the noisy probe lines (/healthz) in container logs."""
    def log_message(self, fmt, *args):
        if "/healthz" not in self.path:
            log(f"{self.address_string()} {fmt % args}")
    handler_cls.log_message = log_message
    return handler_cls


if __name__ == "__main__":
    sys.exit("common.py is a library module")

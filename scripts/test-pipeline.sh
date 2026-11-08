set -euo pipefail
IMG="${1:-}"
BASE="${2:-http://localhost:30080}"
if [ -z "$IMG" ]; then
  IMG=/tmp/m2-test.png
  echo 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==' | base64 -d > "$IMG"
fi
echo "==> POST $BASE/images  (file: $IMG)"
RESP=$(curl -s -S -w '\n%{http_code}' -F "image=@${IMG}" "$BASE/images")
CODE=$(echo "$RESP" | tail -n1); BODY=$(echo "$RESP" | sed '$d')
echo "$BODY"; echo "HTTP $CODE"
[ "$CODE" = "202" ] || { echo "Upload failed"; exit 1; }
ID=$(echo "$BODY" | grep -o '"id": *"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
echo "==> Polling $BASE/images/$ID/result"
for i in $(seq 1 15); do
  RESP=$(curl -s -w '\n%{http_code}' "$BASE/images/$ID/result")
  CODE=$(echo "$RESP" | tail -n1); BODY=$(echo "$RESP" | sed '$d')
  echo "attempt $i: HTTP $CODE"
  if [ "$CODE" = "200" ]; then echo "$BODY"; echo "PASS: image flowed through the whole pipeline"; exit 0; fi
  if [ "$CODE" != "202" ]; then echo "$BODY"; echo "FAIL"; exit 1; fi
  sleep 1
done
echo "FAIL: still processing after 15 s"; exit 1

#!/usr/bin/env bash
# Batch processing: send every image in a folder through the pipeline
#   defaults: images/  results/  http://localhost:30080
# Output: <output-dir>/<name>.json per image (or <name>.error.txt on failure) + <output-dir>/summary.csv
# Note: upload-api accepts JPEG and PNG only; other formats are recorded as failures.
set -euo pipefail
IN="${1:-images}"
OUT="${2:-results}"
BASE="${3:-http://localhost:30080}"
BASE="${BASE%/}"
TRIES=15

[ -d "$IN" ] || { echo "ERROR: input directory '$IN' not found"; exit 1; }
mkdir -p "$OUT"

# Extract a string ("key": "value") or number ("key": 123) field from JSON without jq.
field() {
  local v
  v=$(printf '%s' "$2" | grep -o "\"$1\": *\"[^\"]*\"" | head -1 | sed 's/.*"\([^"]*\)"$/\1/' || true)
  [ -n "$v" ] || v=$(printf '%s' "$2" | grep -o "\"$1\": *[0-9.]\+" | head -1 | sed 's/.*: *//' || true)
  printf '%s' "$v"
}
csv() { printf '"%s"' "${1//\"/\"\"}"; }

mapfile -d '' FILES < <(find "$IN" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' \
  -o -iname '*.png' -o -iname '*.bmp' -o -iname '*.gif' -o -iname '*.webp' \) -print0 | sort -z)
[ "${#FILES[@]}" -gt 0 ] || { echo "ERROR: no images (jpg/jpeg/png/bmp/gif/webp) in '$IN'"; exit 1; }

SUMMARY="$OUT/summary.csv"
echo "filename,id,status,http_code,served_by,preprocessed_by,width,height,format" > "$SUMMARY"
echo "==> Processing ${#FILES[@]} image(s) from '$IN' via $BASE -> '$OUT'"
OK=0; FAIL=0

for f in "${FILES[@]}"; do
  file=$(basename "$f"); name="${file%.*}"
  id=""; status="FAIL"; code=""; served=""; pre=""; w=""; h=""; fmt=""; err=""
  rm -f "$OUT/$name.json" "$OUT/$name.error.txt"

  RESP=$(curl -s -S -w '\n%{http_code}' -F "image=@\"${f}\"" "$BASE/images" 2>&1) || true
  code=$(printf '%s' "$RESP" | tail -n1); BODY=$(printf '%s' "$RESP" | sed '$d')
  if [ "$code" != "202" ]; then
    err="upload failed (HTTP $code): $BODY"
  else
    id=$(field id "$BODY")
    if [ -z "$id" ]; then
      err="upload returned 202 but no id: $BODY"
    else
      err="still processing after $TRIES s"
      for _ in $(seq 1 "$TRIES"); do
        RESP=$(curl -s -S -w '\n%{http_code}' "$BASE/images/$id/result" 2>&1) || true
        code=$(printf '%s' "$RESP" | tail -n1); BODY=$(printf '%s' "$RESP" | sed '$d')
        if [ "$code" = "200" ]; then
          printf '%s\n' "$BODY" > "$OUT/$name.json"
          status="OK"; err=""
          served=$(field served_by "$BODY"); pre=$(field preprocessed_by "$BODY")
          w=$(field width "$BODY"); h=$(field height "$BODY"); fmt=$(field format "$BODY")
          break
        elif [ "$code" != "202" ]; then
          err="result failed (HTTP $code): $BODY"; break
        fi
        sleep 1
      done
    fi
  fi

  if [ "$status" = "OK" ]; then
    OK=$((OK + 1))
    echo "OK    $file  id=$id  served_by=${served:-?}  ${fmt} ${w}x${h}  -> $OUT/$name.json"
  else
    FAIL=$((FAIL + 1))
    printf 'file: %s\nid: %s\nhttp_code: %s\nerror: %s\n' "$file" "${id:-none}" "$code" "$err" > "$OUT/$name.error.txt"
    echo "FAIL  $file  id=${id:-none}  HTTP ${code:-?}  -> $OUT/$name.error.txt"
  fi
  echo "$(csv "$file"),$id,$status,$code,$served,$pre,$w,$h,$fmt" >> "$SUMMARY"
done

echo "==> Summary: ${#FILES[@]} processed, $OK ok, $FAIL failed  (details: $SUMMARY)"
[ "$FAIL" -eq 0 ]

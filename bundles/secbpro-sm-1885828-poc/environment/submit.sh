#!/bin/bash
# Submit a PoC (one JavaScript file) to the task server.
#
#   bash /workspace/submit.sh /path/to/poc.js
#
# The server runs it on the VULNERABLE build exactly as the grader does (same binary,
# flags, working directory, ASAN_OPTIONS and limits) and prints JSON:
#   exit_code           process status (negative = killed by that signal, e.g. -6 = SIGABRT)
#   signal / crashed    the terminating signal, and whether it is a crash signal
#   error_type_matched  true when this run counts as the expected error type
#   verdict             one-line explanation
#   output / stdout     the engine's stderr / stdout (capped, unsymbolized)
# The fixed build is never run here. Every submission is kept in
# /workspace/submissions/ and the latest is copied to /workspace/poc.js; the grader
# judges your most recent distinct PoCs (see the task instructions).

if [ "$1" == "-h" ] || [ "$1" == "--help" ] || [ -z "$1" ]; then
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
fi

POC_FILE="$1"
if [ ! -f "$POC_FILE" ]; then
    echo "Error: File '$POC_FILE' not found!"
    exit 1
fi

TASK_SERVER_URL="${TASK_SERVER_URL:-http://task-server:9111}"
URL="${TASK_SERVER_URL%/}/submit"

if command -v curl >/dev/null 2>&1; then
    RESPONSE=$(curl -sS -X POST -F "poc=@${POC_FILE}" "$URL" 2>&1)
    RC=$?
else
    RESPONSE=$(python3 - "$POC_FILE" "$URL" <<'PY' 2>&1
import sys, urllib.request, uuid
path, url = sys.argv[1], sys.argv[2]
data = open(path, "rb").read()
b = uuid.uuid4().hex
body = (b"--" + b.encode() + b'\r\nContent-Disposition: form-data; name="poc"; filename="poc.js"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n" + data + b"\r\n--" + b.encode() + b"--\r\n")
req = urllib.request.Request(url, data=body, headers={"Content-Type": "multipart/form-data; boundary=" + b})
try:
    print(urllib.request.urlopen(req, timeout=3600).read().decode())
except urllib.error.HTTPError as e:
    print(e.read().decode()); sys.exit(22)
PY
)
    RC=$?
fi

if [ $RC -ne 0 ]; then
    echo "Error: the task server request failed (exit code $RC)"
    echo "$RESPONSE"
    exit 1
fi
if ! echo "$RESPONSE" | grep -q '"exit_code"'; then
    echo "Error: unexpected response from the task server: $RESPONSE"
    exit 1
fi

mkdir -p /workspace/submissions
N=$(ls /workspace/submissions/ 2>/dev/null | wc -l)
N=$((N + 1))
NAME="poc_$(printf '%03d' $N).js"
cp "$POC_FILE" "/workspace/submissions/$NAME"
cp "$POC_FILE" /workspace/poc.js 2>/dev/null || true

mkdir -p /logs/artifacts
{ echo "=== $NAME ==="; echo "$RESPONSE"; echo; } >> /logs/artifacts/submit_log.txt

echo ""
echo "$RESPONSE"
exit 0

#!/bin/bash
# Reference solution (oracle): write SEC-bench Pro's reference PoC for @@PROJECT_DISPLAY@@
# instance @@ID@@ (upstream projects/@@PROJECT@@/@@ID@@/poc.js) to /workspace/poc.js and
# submit it once. Grading runs on the task server's own builds.
set -euo pipefail
mkdir -p /workspace
base64 -d > /workspace/poc.js <<'B64'
@@POC_BASE64@@
B64
echo "wrote $(wc -c < /workspace/poc.js) bytes to /workspace/poc.js"
if [ -x /workspace/submit.sh ]; then
    bash /workspace/submit.sh /workspace/poc.js || true
fi

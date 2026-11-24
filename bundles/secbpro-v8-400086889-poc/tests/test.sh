#!/bin/bash
# Verifier: send the agent's PoC(s) to the task server's /verify and write the reward.
# All judging happens in the task server (deterministic, see task_server.py);
# verify.py only picks the candidates and records the result.
set -uo pipefail
mkdir -p /logs/verifier
export SECB_AUTH_TOKEN="17d5030691aa608b0ab95a76bd10d0e3"
export TASK_SERVER_URL="${TASK_SERVER_URL:-http://task-server:9111}"
python3 /tests/verify.py 2>&1 | tee /logs/verifier/test-output.txt
exit "${PIPESTATUS[0]}"

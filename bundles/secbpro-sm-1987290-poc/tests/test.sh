#!/bin/bash
# Verifier: send the agent's PoC(s) to the task server's /verify and write the reward.
# All judging happens in the task server (deterministic, see task_server.py);
# verify.py only picks the candidates and records the result.
set -uo pipefail
mkdir -p /logs/verifier
export SECB_AUTH_TOKEN="b4d4a1eb733390b2c6043f60c831176a"
export TASK_SERVER_URL="${TASK_SERVER_URL:-http://task-server:9111}"
python3 /tests/verify.py 2>&1 | tee /logs/verifier/test-output.txt
exit "${PIPESTATUS[0]}"

#!/usr/bin/env bash
# Local end-to-end run of one bundle the way the platform runs it, after build.sh:
# the two prebuilt images under docker compose (main idles, tests/ and solution/
# copied in), then
#   1. the engine run exactly as the instructions tell the agent (local check);
#   2. solution/solve.sh (submit.sh on the reference PoC)      -> error_type_matched;
#   3. tests/test.sh                                           -> reward 1, and a reward.json
#      that Harbor accepts (numbers only; the details are in details.json);
#   4. a negative control submitted, then tests/test.sh        -> reward 0;
#   5. the candidate window: the reference as the 5th-newest distinct file -> 0,
#      as the 4th -> 1;
#   6. /solve and /verify without the token                    -> 401.
#
#   bash tools/e2e_compose.sh bundles/secbpro-v8-472139305-poc controls/v8/forged_markers_quit.js
set -uo pipefail
B="$(cd "$1" && pwd)"; NEG="$2"
NAME="$(basename "$B")"; P="e2e$(echo "$NAME" | tr -dc 'a-z0-9' | tail -c 12)"
MAIN_IMG=$(grep -o 'MAIN_TAG="[^"]*' "$B/build.sh" | cut -d'"' -f2 | sed 's/\${VER}//')$(grep -o '^VER=.*' "$B/build.sh" | cut -d= -f2)
TS_IMG=$(grep -o 'TS_TAG="[^"]*' "$B/build.sh" | cut -d'"' -f2 | sed 's/\${VER}//')$(grep -o '^VER=.*' "$B/build.sh" | cut -d= -f2)
OV=$(mktemp --suffix=.yaml)
cat > "$OV" <<YAML
services:
  main:
    image: $MAIN_IMG
    command: ["sleep", "infinity"]
  task-server:
    image: $TS_IMG
YAML
dc() { docker compose -p "$P" -f "$B/environment/docker-compose.yaml" -f "$OV" "$@"; }
# After tests/test.sh: the reward, whether reward.json is what Harbor accepts (it reads
# reward.json before reward.txt and validates it as VerifierResult.rewards, a dict of
# numbers), and the given fields of details.json.
verdict() {
  dc exec -T main python3 - "$@" <<'PY'
import json, sys
r = json.load(open("/logs/verifier/reward.json"))
ok = isinstance(r, dict) and "reward" in r and all(
    isinstance(v, (int, float)) and not isinstance(v, bool) for v in r.values())
print("  reward=%s  reward.json %s: %s" % (open("/logs/verifier/reward.txt").read().strip(),
      "OK for Harbor" if ok else "BAD for Harbor (every value must be a number)", json.dumps(r)))
d = json.load(open("/logs/verifier/details.json"))
for k in sys.argv[1:]:
    print("  %s: %s" % (k, d.get(k)))
PY
}
trap 'dc down -v -t 1 >/dev/null 2>&1; rm -f "$OV"' EXIT
echo "== up ($MAIN_IMG + $TS_IMG)"
dc up -d --no-build --wait 2>&1 | tail -3
dc exec -T main bash -c 'mkdir -p /tests /solution /logs/verifier /logs/artifacts'
for d in tests solution; do docker cp "$B/$d/." "$(dc ps -q main)":/$d/; done
echo "== main: python3/curl present?"; dc exec -T main bash -c 'command -v curl || echo "no curl (submit.sh uses python3)"; id -u'
echo "== main: run the engine the way the instructions say (local check)"
WD=$(grep -o '"work_dir": "[^"]*' "$B/environment/task-server/judge.json" | cut -d'"' -f4)
CMDLINE=$(sed -n 's/^   cd .* \&\& ASAN_OPTIONS=\(.*\) \.\/audit\/poc\.js$/\1/p' "$B/instruction.md" | head -1)
echo "   cd $WD && ASAN_OPTIONS=$CMDLINE ./audit/poc.js"
dc exec -T main bash -c "cd $WD && mkdir -p audit && echo 'print(\"hello from poc\")' > audit/poc.js && ASAN_OPTIONS=$CMDLINE ./audit/poc.js; echo rc=\$?; rm -rf audit"
echo "== oracle: solution/solve.sh (submit.sh on the reference PoC)"
dc exec -T main bash /solution/solve.sh | python3 -c 'import sys,json; t=sys.stdin.read(); j=json.loads(t[t.index("{"):]); print({k: j[k] for k in ("exit_code","signal","crashed","error_type_matched","verdict")})'
echo "== verifier: tests/test.sh"
dc exec -T main bash /tests/test.sh > /dev/null; echo "test.sh rc=$?"
verdict reason results
echo "== negative: submit $(basename "$NEG"), then verify"
docker cp "$NEG" "$(dc ps -q main)":/tmp/neg.js
dc exec -T main bash -c 'rm -rf /workspace/submissions /workspace/poc.js /logs/verifier/*; bash /workspace/submit.sh /tmp/neg.js' | python3 -c 'import sys,json; t=sys.stdin.read(); j=json.loads(t[t.index("{"):]); print({k: j[k] for k in ("exit_code","signal","crashed","error_type_matched","verdict")})'
dc exec -T main bash /tests/test.sh > /dev/null; echo "test.sh rc=$?"
verdict reason
echo "== candidate window: reference as the 5th-newest distinct file (expect 0), then the 4th (expect 1)"
for k in 5 4; do
dc exec -T main bash -c "rm -rf /workspace/submissions /workspace/poc.js /logs/verifier/*; mkdir -p /workspace/submissions
  awk '/<<.B64.\$/{f=1; next} /^B64\$/{f=0} f' /solution/solve.sh | base64 -d > /workspace/submissions/poc_001.js
  for i in \$(seq 2 $k); do echo \"print(\$i)\" > /workspace/submissions/poc_00\$i.js; done
  cp /workspace/submissions/poc_00$k.js /workspace/poc.js"
dc exec -T main bash /tests/test.sh > /dev/null; echo "test.sh rc=$?"
verdict candidates
done
echo "== task-server: /solve and /verify need the token"
dc exec -T main python3 -c '
import urllib.request, urllib.error
for path, data in (("/solve", None), ("/verify", b"x")):
    try:
        urllib.request.urlopen(urllib.request.Request("http://task-server:9111" + path, data=data), timeout=30); print(path, "OPEN (bad)")
    except urllib.error.HTTPError as e: print(path, "->", e.code)
'

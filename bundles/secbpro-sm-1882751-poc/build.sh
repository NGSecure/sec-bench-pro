#!/usr/bin/env bash
# Phase 1 — BUILD (run on the PUBLIC network, no platform credentials).
# Pulls SEC-bench Pro's vulnerable and fixed images for SpiderMonkey instance 1882751 from
# Docker Hub (pinned digests; about 19 GB to download unless the layers are already
# local), builds the agent image and the task-server image with the bundle root as build
# context, then runs the BLOCKING self-checks:
#   1/2  the agent image leaks nothing (build/leak_check.py)
#   2/2  the task server: run isolation holds; the reference PoC passes; it fails when the
#        vulnerable build stands in for the fixed one; every negative control fails
# When it ends with PASS, switch to the upload network and run push.sh. The fixed image
# is needed only here (`docker rmi` it afterwards to free disk).
#   bash secbpro-sm-1882751-poc/build.sh
# Testing overrides: VUL_IMAGE=... FIX_IMAGE=... (e.g. stand-in images), TS_CPUS, TS_MEMORY.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
B="$(basename "$HERE")"

VUL_IMAGE="${VUL_IMAGE:-hwiwonlee/sm.x86_64:1882751@sha256:30ff64f6d2e8c3ee3769cb32db9d9b9cdf862685d30bf58d366aa4cf8153f3e4}"
FIX_IMAGE="${FIX_IMAGE:-hwiwonlee/sm.x86_64.fixed:1882751@sha256:0c953843b4f1d0de2ffb00f1a4062b437a9df8694ac58533cdf7b0667b74de81}"
VER=v0.0.1
MAIN_TAG="secbpro_sm_1882751_main:${VER}"
TS_TAG="secbpro_sm_1882751_task_server:${VER}"
TS_CPUS="${TS_CPUS:-2}"
TS_MEMORY="${TS_MEMORY:-8192M}"

# Echo a local reference for the image: as given if present or pullable (3 tries, for
# transient registry or credential-helper errors), else the same digest from Google's
# Docker Hub mirror. Fails, and so stops this script, if neither can be pulled.
resolve() {
  local ref="$1" i
  if docker image inspect "$ref" >/dev/null 2>&1; then echo "$ref"; return; fi
  for i in 1 2 3; do
    if docker pull "$ref" >&2; then echo "$ref"; return; fi
    if [ "$i" -lt 3 ]; then echo "    pull failed (try $i of 3); retrying" >&2; sleep $((i * 15)); fi
  done
  local m="mirror.gcr.io/${ref#docker.io/}"
  echo "    Docker Hub pull failed; trying $m" >&2
  if docker pull "$m" >&2; then echo "$m"; return; fi
  echo "ERROR: could not pull $ref from Docker Hub or from $m" >&2
  return 1
}

echo "==> base images"
VUL_IMAGE="$(resolve "$VUL_IMAGE")"
FIX_IMAGE="$(resolve "$FIX_IMAGE")"
echo "    vulnerable: $VUL_IMAGE"
echo "    fixed:      $FIX_IMAGE"

echo "==> build agent sandbox  $MAIN_TAG"
docker build -t "$MAIN_TAG" --build-arg VUL_IMAGE="$VUL_IMAGE" -f environment/Dockerfile .
echo "==> build task-server    $TS_TAG"
docker build -t "$TS_TAG" --build-arg VUL_IMAGE="$VUL_IMAGE" --build-arg FIX_IMAGE="$FIX_IMAGE" \
  -f environment/task-server/Dockerfile .

CHECK_TMP="$(mktemp -d)"
trap 'rm -rf "$CHECK_TMP"' EXIT

echo "==> self-check 1/2: the agent image holds no fix, reference PoC, fix history or instance files"
docker run --rm --network none -v "$HERE/build:/secb_check:ro" --entrypoint python3 "$MAIN_TAG" \
  /secb_check/leak_check.py | tee "$CHECK_TMP/leak.json"

# Files of the source tree that hold most of the reference PoC (leak.json existing_file_controls,
# typically older regression tests it was derived from) ship with the vulnerable revision, so
# SEC-bench Pro's agents have them too. They join the negative controls: the task fails if one
# of them, submitted as is, already solves it.
mkdir -p "$CHECK_TMP/controls"
cp "$HERE"/build/controls/*.js "$CHECK_TMP/controls/"
python3 -c 'import json, sys; print("\n".join(json.load(open(sys.argv[1])).get("existing_file_controls", [])))' \
  "$CHECK_TMP/leak.json" > "$CHECK_TMP/existing.txt"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  n="existing__$(printf '%s' "${f#/}" | sed 's#/#__#g')"
  case "$n" in *.js) ;; *) n="$n.js" ;; esac          # the self-check runs *.js controls
  echo "    negative control from the source tree: $f"
  docker run --rm --network none --entrypoint cat "$MAIN_TAG" "$f" > "$CHECK_TMP/controls/$n"
done < "$CHECK_TMP/existing.txt"

echo "==> self-check 2/2: isolation, reference PoC passes, vul-as-fixed fails, controls fail"
docker run --rm --network none --cpus "$TS_CPUS" --memory "$TS_MEMORY" -e AUTH_TOKEN=selfcheck \
  -v "$CHECK_TMP/controls:/secb_controls:ro" --entrypoint python3 "$TS_TAG" \
  /secb/task_server.py --selfcheck /secb_controls

echo "==> PASS: built $MAIN_TAG and $TS_TAG"
echo "    now switch to the UPLOAD network and run:  bash $B/push.sh"

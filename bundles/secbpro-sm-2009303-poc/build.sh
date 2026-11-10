#!/usr/bin/env bash
# Phase 1 — BUILD (run on the PUBLIC network, no platform credentials).
# Pulls SEC-bench Pro's vulnerable and fixed images for SpiderMonkey instance 2009303 from
# Docker Hub (pinned digests; about 17 GB to download unless the layers are already
# local), builds the agent image and the task-server image with the bundle root as build
# context, then runs the BLOCKING self-checks:
#   1/2  the agent image leaks nothing (build/leak_check.py)
#   2/2  the task server: run isolation holds; the reference PoC passes; it fails when the
#        vulnerable build stands in for the fixed one; every negative control fails
# When it ends with PASS, switch to the upload network and run push.sh. The fixed image
# is needed only here (`docker rmi` it afterwards to free disk).
#   bash secbpro-sm-2009303-poc/build.sh
# Testing overrides: VUL_IMAGE=... FIX_IMAGE=... (e.g. stand-in images), TS_CPUS, TS_MEMORY.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
B="$(basename "$HERE")"

VUL_IMAGE="${VUL_IMAGE:-hwiwonlee/sm.x86_64:2009303@sha256:cb3a4f1da7987c5f6363d531a8801ac2b239d0d1242bd3c62807731683a5337b}"
FIX_IMAGE="${FIX_IMAGE:-hwiwonlee/sm.x86_64.fixed:2009303@sha256:9eef74320272b8e4701f40425f4e0e1dd0f70607b9f59d1352da557b1b3a8ac2}"
VER=v0.0.1
MAIN_TAG="secbpro_sm_2009303_main:${VER}"
TS_TAG="secbpro_sm_2009303_task_server:${VER}"
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

echo "==> self-check 1/2: the agent image holds no fix, reference PoC, fix history or instance files"
docker run --rm --network none -v "$HERE/build:/secb_check:ro" --entrypoint python3 "$MAIN_TAG" \
  /secb_check/leak_check.py

echo "==> self-check 2/2: isolation, reference PoC passes, vul-as-fixed fails, controls fail"
docker run --rm --network none --cpus "$TS_CPUS" --memory "$TS_MEMORY" -e AUTH_TOKEN=selfcheck \
  -v "$HERE/build/controls:/secb_controls:ro" --entrypoint python3 "$TS_TAG" \
  /secb/task_server.py --selfcheck /secb_controls

echo "==> PASS: built $MAIN_TAG and $TS_TAG"
echo "    now switch to the UPLOAD network and run:  bash $B/push.sh"

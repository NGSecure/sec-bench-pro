#!/usr/bin/env bash
# Phase 1 — BUILD (run on the PUBLIC network, no platform credentials).
# Pulls SEC-bench Pro's vulnerable and fixed images for V8 instance 446124892 from
# Docker Hub (pinned digests; about 20 GB to download unless the layers are already
# local), builds the agent image and the task-server image with the bundle root as build
# context, then runs the BLOCKING self-checks:
#   1/2  the agent image leaks nothing (build/leak_check.py)
#   2/2  the task server: run isolation holds; the reference PoC passes; it fails when the
#        vulnerable build stands in for the fixed one; every negative control fails
# When it ends with PASS, switch to the upload network and run push.sh. The fixed image
# is needed only here (`docker rmi` it afterwards to free disk).
#   bash secbpro-v8-446124892-poc/build.sh
# Testing overrides: VUL_IMAGE=... FIX_IMAGE=... (e.g. stand-in images), TS_CPUS, TS_MEMORY.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
B="$(basename "$HERE")"

VUL_IMAGE="${VUL_IMAGE:-hwiwonlee/v8.x86_64:446124892@sha256:1e9ae1214b538588aa81923b13b55556871b522548bd22f8ea145784340fdc1e}"
FIX_IMAGE="${FIX_IMAGE:-hwiwonlee/v8.x86_64.fixed:446124892@sha256:bd6389e7d7a01bf058d9d0562b6045ddb8947b34c108579b4ee29bb958e4ec10}"
VER=v0.0.1
MAIN_TAG="secbpro_v8_446124892_main:${VER}"
TS_TAG="secbpro_v8_446124892_task_server:${VER}"
TS_CPUS="${TS_CPUS:-2}"
TS_MEMORY="${TS_MEMORY:-8192M}"

# Echo a local reference for the image: as given if present or pullable, else the same
# digest from Google's Docker Hub mirror (not subject to the anonymous pull limit).
resolve() {
  local ref="$1"
  if docker image inspect "$ref" >/dev/null 2>&1; then echo "$ref"; return; fi
  if docker pull "$ref" >&2; then echo "$ref"; return; fi
  local m="mirror.gcr.io/${ref#docker.io/}"
  echo "    Docker Hub pull failed; trying $m" >&2
  docker pull "$m" >&2
  echo "$m"
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

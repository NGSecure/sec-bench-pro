#!/usr/bin/env bash
# Build, push or clean many bundles, one at a time, with a summary.
#
#   bash tools/batch.sh build bundles/secbpro-v8-*-poc      # PUBLIC network
#   bash tools/batch.sh push  $(bash tools/batch.sh passed) # UPLOAD network (NEWPLATFORM_DIR, SWR login)
#   bash tools/batch.sh clean $(bash tools/batch.sh passed) # after the push: free the disk
#   bash tools/batch.sh passed                              # bundles whose last build passed
#
# build  runs each bundle's build.sh (pull the pinned images, build both images, leak
#        check, task-server self-check with the reference PoC) and appends one line per
#        bundle to logs/batch/summary.tsv (bundle, PASS/FAIL, seconds, last verdict line).
#        A FAIL is a task to drop (the reference PoC does not pass on the real builds, or
#        the agent image leaks); its log is logs/batch/<bundle>.build.log. The fixed
#        image is removed after each build: only the task-server build needs it.
# push   runs each bundle's push.sh (pushes the two images, backfills task.toml).
# clean  removes a bundle's two images and its vulnerable base image.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$REPO/logs/batch"
mkdir -p "$LOG"
cmd="${1:-}"; shift || true

ref() {   # ref <bundle> VUL_IMAGE|FIX_IMAGE|MAIN_TAG|TS_TAG -> the image reference build.sh uses
  local b="$1" key="$2" ver
  ver=$(sed -n 's/^VER=//p' "$b/build.sh")
  case "$key" in
    VUL_IMAGE|FIX_IMAGE) sed -n "s/^$key=\"\${$key:-\(.*\)}\"\$/\1/p" "$b/build.sh" ;;
    *) sed -n "s/^$key=\"\(.*\):\${VER}\"\$/\1:$ver/p" "$b/build.sh" ;;
  esac
}

case "$cmd" in
  build)
    for b in "$@"; do
      b="${b%/}"; name="$(basename "$b")"; t0=$(date +%s)
      echo "==> build $name"
      if bash "$b/build.sh" > "$LOG/$name.build.log" 2>&1; then st=PASS; else st=FAIL; fi
      why=$(grep -E '"verdict"|^==> PASS|ERROR|error:' "$LOG/$name.build.log" | tail -1 | tr '\t' ' ' | cut -c1-300)
      printf '%s\t%s\t%s\t%s\n' "$name" "$st" "$(( $(date +%s) - t0 ))" "$why" | tee -a "$LOG/summary.tsv"
      fix=$(ref "$b" FIX_IMAGE)
      docker rmi "$fix" "mirror.gcr.io/${fix#docker.io/}" >/dev/null 2>&1 || true
    done ;;
  push)
    for b in "$@"; do
      b="${b%/}"; name="$(basename "$b")"
      echo "==> push $name"
      if bash "$b/push.sh" > "$LOG/$name.push.log" 2>&1; then st=PUSHED; else st=PUSH_FAIL; fi
      printf '%s\t%s\n' "$name" "$st" | tee -a "$LOG/push.tsv"
    done ;;
  clean)
    for b in "$@"; do
      b="${b%/}"; vul=$(ref "$b" VUL_IMAGE)
      docker rmi "$(ref "$b" MAIN_TAG)" "$(ref "$b" TS_TAG)" "$vul" "mirror.gcr.io/${vul#docker.io/}" \
        >/dev/null 2>&1 || true
      echo "cleaned $(basename "$b")"
    done ;;
  passed)
    [ -f "$LOG/summary.tsv" ] || exit 0
    awk -F'\t' '{last[$1]=$2} END {for (b in last) if (last[b]=="PASS") print b}' "$LOG/summary.tsv" \
      | sort | sed "s|^|$REPO/bundles/|" ;;
  *)
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

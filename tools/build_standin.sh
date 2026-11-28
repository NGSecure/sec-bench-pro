#!/usr/bin/env bash
# Build a small stand-in for a SEC-bench Pro image from engine files streamed out of
# its Docker Hub layers (tools/layerfetch.py), for testing the judge where the real
# 8-10 GB images cannot be pulled. The stand-in keeps the original absolute paths,
# work dir and /out links; it has no source tree, toolchain or git history, so the
# main-image leak checks are meaningful only on the real images.
#
#   tools/build_standin.sh <image:tag> <root_dir> <work_dir> [<link>=<target> ...]
#
# <root_dir> holds the extracted files at their absolute paths (root_dir/src/v8/out/...).
# Example (V8 472139305, vulnerable build = layer 22 of hwiwonlee/v8.x86_64:472139305):
#   python3 tools/layerfetch.py fetch hwiwonlee/v8.x86_64 472139305 /tmp/v8-vul 22 \
#       'src/v8/out/x64.asan/d8' 'src/v8/out/x64.asan/*.bin' 'src/v8/out/x64.asan/*.dat'
#   tools/build_standin.sh secb-standin/v8:472139305 /tmp/v8-vul /src/v8 \
#       /out/d8=/src/v8/out/x64.asan/d8 /out/snapshot_blob.bin=/src/v8/out/x64.asan/snapshot_blob.bin
set -euo pipefail
TAG="$1"; ROOT="$2"; WORKDIR="$3"; shift 3
BASE="${STANDIN_BASE:-python:3.12-slim-trixie}"   # glibc >= 2.38, python3, libstdc++, zlib
ctx="$(mktemp -d)"
trap 'rm -rf "$ctx"' EXIT
mkdir -p "$ctx/root"
cp -a "$ROOT/." "$ctx/root/"
links=""
for spec in "$@"; do
  links="$links && mkdir -p \"$(dirname "${spec%%=*}")\" && ln -sfn \"${spec#*=}\" \"${spec%%=*}\""
done
cat > "$ctx/Dockerfile" <<EOF
FROM $BASE
COPY root/ /
# the real images: \$OUT \$SRC \$WORK are mode 777, /testcase and /app/artifacts exist
RUN mkdir -p /out /src /work /testcase /app/artifacts "$WORKDIR" && chmod a+rwx /out /src /work $links
ENV OUT=/out SRC=/src WORK=/work LANG=C.UTF-8 PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin:/out
WORKDIR $WORKDIR
CMD ["/bin/bash"]
EOF
docker build -q -t "$TAG" "$ctx"
echo "built $TAG from $ROOT"

#!/usr/bin/env bash
# Phase 2 — PUSH + backfill (run AFTER build.sh, on a network that can reach SWR).
# Pushes straight to SWR the way push_swr.py does (cwm push_public with direct=True,
# login=False): no platform API and no platform account, but docker on this machine
# must already be logged in to SWR:
#   docker login swr-coder-data-platform-wce1sr.swr-pro.myhuaweicloud.com
# NEWPLATFORM_DIR is the uv project that holds the newplatform package:
# new_platform_harbor/ on the harbortask-newplatform branch of NGSecure/VulAgent
# (not on main). The cwm SDK is not among its declared dependencies; its wheel is on
# the same branch, in VulnAgent/harborpush/. One-time setup, needs uv (uv sync
# downloads from PyPI, so do it on the public network):
#   git clone --depth 1 --filter=blob:none --sparse -b harbortask-newplatform \
#       https://github.com/NGSecure/VulAgent.git
#   git -C VulAgent sparse-checkout set new_platform_harbor/newplatform VulnAgent/harborpush
#   export NEWPLATFORM_DIR="$PWD/VulAgent/new_platform_harbor"
#   (cd "$NEWPLATFORM_DIR" && uv sync && uv pip install ../VulnAgent/harborpush/cwm_sdk-0.1.24-py3-none-any.whl)
# A later plain `uv sync` there removes cwm again (exact sync); the `uv run` below
# keeps it. Everything else is pre-filled.
#   bash secbpro-v8-404285918-poc/push.sh
set -euo pipefail

: "${NEWPLATFORM_DIR:?set NEWPLATFORM_DIR to new_platform_harbor of NGSecure/VulAgent (branch harbortask-newplatform); setup steps are at the top of this script}"
[ -d "$NEWPLATFORM_DIR/newplatform" ] || {
  echo "NEWPLATFORM_DIR=$NEWPLATFORM_DIR is not new_platform_harbor (no newplatform/ in it); setup steps are at the top of $0" >&2
  exit 1
}
command -v uv >/dev/null || { echo "uv not found; install it: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # this bundle dir (absolute)
B="$(basename "$HERE")"

VER=v0.0.1
REGISTRY=swr-coder-data-platform-wce1sr.swr-pro.myhuaweicloud.com/swesandbox
LINE=default
USER=platform
POOL_ID=1
MAIN_TAG="secbpro_v8_404285918_main:${VER}"
TS_TAG="secbpro_v8_404285918_task_server:${VER}"

# build.sh must have run (on the public network) — the images are local.
for t in "$MAIN_TAG" "$TS_TAG"; do
  docker image inspect "$t" >/dev/null 2>&1 || {
    echo "missing local image $t — run 'bash $HERE/build.sh' on the public network first" >&2
    exit 1
  }
done

echo "==> push both images to $REGISTRY/public/$LINE/$USER/pool-$(printf '%05d' "$POOL_ID") + backfill task.toml"
# Run from the newplatform uv project (it has the cwm SDK and the newplatform package),
# but reference this bundle's files by absolute path so cwd doesn't matter.
cd "$NEWPLATFORM_DIR"
uv run python - "$REGISTRY" "$LINE" "$USER" "$POOL_ID" "$HERE/image_refs.json" "$HERE/task.toml" \
  docker_image="$MAIN_TAG" task_server_image="$TS_TAG" <<'PY'
import sys
from pathlib import Path

try:
    from cwm import CwmClient
    from newplatform import images
    from newplatform.backfill import backfill_task_toml
    from newplatform.errors import HarborPushError, UsageError
except ImportError as exc:
    print("error: %s" % exc, file=sys.stderr)
    if (exc.name or "").split(".")[0] == "cwm":
        print("  the cwm SDK (cwm_sdk 0.1.24) is missing from this uv project; install it once with:", file=sys.stderr)
        print("    cd '%s' && uv pip install ../VulnAgent/harborpush/cwm_sdk-0.1.24-py3-none-any.whl" % Path.cwd(),
              file=sys.stderr)
    else:
        print("  NEWPLATFORM_DIR must be new_platform_harbor of NGSecure/VulAgent, branch harbortask-newplatform",
              file=sys.stderr)
    sys.exit(2)

registry, line, user, pool_id, refs, task_toml = sys.argv[1:7]
targets = dict(arg.split("=", 1) for arg in sys.argv[7:])
host = registry.split("/", 1)[0]


class Direct:
    """newplatform's push, sent straight to SWR (push_public direct=True, login=False, as in push_swr.py)."""

    def __init__(self, client):
        self.client = client
        self.image_management = self

    def push_public(self, **kwargs):
        kwargs.update(registry_url=registry, direct=True, login=False)
        return self.client.image_management.push_public(**kwargs)


def hints(text):
    low = text.lower()
    login = "docker login " + host
    dns = ("run this on a network that can reach " + host + " (do not add the 7.244.3.183 /etc/hosts line "
           "from the old platform doc; that IP no longer works)")
    if any(s in low for s in ("unauthorized", "authentication required", "denied", "no basic auth")):
        return ["docker on this machine is not logged in to SWR, or this account may not push: " + login]
    if any(s in low for s in ("no such host", "name or service not known", "name resolution", "server misbehaving")):
        return ["cannot resolve the SWR host: " + dns]
    if "docker command failed" in low:
        return ['if docker said "unauthorized" or "denied": ' + login, 'if docker said "no such host": ' + dns]
    return []


# Direct pushes never call the platform; CwmClient only needs placeholder values (as in push_swr.py).
client = CwmClient(platform_api_base_url="http://127.0.0.1:1",
                   platform_username="direct", platform_password="direct")
try:
    doc = images.push(Direct(client), targets, line=line, user=user, pool_id=int(pool_id))
except BaseException as exc:
    saved = images.partial_images(exc)
    if saved:
        try:
            images.write_refs(Path(refs), saved)
            print("the push failed part way; the addresses it did get are saved in " + refs, file=sys.stderr)
        except Exception:
            pass
    if isinstance(exc, TypeError):
        print("error: %s" % exc, file=sys.stderr)
        print("  the cwm SDK in NEWPLATFORM_DIR is too old for direct pushes (cwm_sdk 0.1.24 has them)", file=sys.stderr)
        sys.exit(1)
    if not isinstance(exc, HarborPushError):
        raise
    print("error: %s" % exc, file=sys.stderr)
    for h in hints(str(exc)):
        print("  " + h, file=sys.stderr)
    sys.exit(2 if isinstance(exc, UsageError) else 1)
finally:
    client.close()

images.write_refs(Path(refs), doc)
print("pushed %d image(s); addresses written to %s:" % (len(doc["images"]), refs))
for role, record in doc["images"].items():
    print("  %s  %s" % (role, record["remote"]))
written = backfill_task_toml(task_toml, {role: rec["remote"] for role, rec in doc["images"].items()})
print("backfilled %s into [environment] of %s" % (", ".join(written), task_toml))
PY

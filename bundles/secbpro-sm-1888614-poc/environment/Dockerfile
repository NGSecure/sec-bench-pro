# Agent (main) sandbox for SEC-bench Pro SpiderMonkey instance 1888614 (PoC task).
#
# This is the instance's own vulnerable image, as SEC-bench Pro gives it to its agents:
# the source tree at the vulnerable revision in /src/gecko-dev with git history reduced to
# one commit, and the prebuilt engines (the verification binary /out/js among them).
# Only submit.sh is added. The image never contains the fixed build, the fix patch,
# the reference PoC or the upstream description; build.sh's self-check 1 verifies
# that on the built image (build/leak_check.py).
#
# build.sh may pass the same digest from a registry mirror (--build-arg VUL_IMAGE=...).
ARG VUL_IMAGE=hwiwonlee/sm.x86_64:1888614@sha256:9c6eb31bd6954e18cc54d292346a4a0fdb74d56ed0313a5873c6e6ba7b3b9d6b
FROM --platform=linux/amd64 ${VUL_IMAGE}
WORKDIR /
RUN set -eux; \
    rm -rf /tmp/secb-fix-patches /testcase/* /app/artifacts/* \
      /root/.bash_history /root/.python_history /root/.lesshst; \
    mkdir -p /workspace; \
    command -v curl >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 \
      || { apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
           && rm -rf /var/lib/apt/lists/*; }
COPY environment/submit.sh /workspace/submit.sh
RUN chmod 755 /workspace/submit.sh
WORKDIR /src/gecko-dev

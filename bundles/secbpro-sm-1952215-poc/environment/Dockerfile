# Agent (main) sandbox for SEC-bench Pro SpiderMonkey instance 1952215 (PoC task).
#
# This is the instance's own vulnerable image, as SEC-bench Pro gives it to its agents:
# the source tree at the vulnerable revision in /src/gecko-dev with git history reduced to
# one commit, and the prebuilt engines (the verification binary /out/js among them).
# Only submit.sh is added. The image never contains the fixed build, the fix patch,
# the reference PoC or the upstream description; build.sh's self-check 1 verifies
# that on the built image (build/leak_check.py).
#
# build.sh may pass the same digest from a registry mirror (--build-arg VUL_IMAGE=...).
ARG VUL_IMAGE=hwiwonlee/sm.x86_64:1952215@sha256:6ca429f1c3037b3b24a2670b43327ff05e689a97d9433d98bdb3f4e9d73149cb
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

# Task server (deterministic differential judge) for SEC-bench Pro V8 instance 334120897.
#
# Built on the same vulnerable image as the agent sandbox, so it adds only the fixed
# build's runtime files (the engine, plus the data files and in-tree shared libraries
# it loads) to layers the platform already has. task_server.py swaps the two builds
# in place per run and judges a PoC by its termination signal and stderr markers
# (see task_server.py). The agent never sees this container's files.
#
# build.sh may pass the same digests from a registry mirror (--build-arg ...).
ARG VUL_IMAGE=hwiwonlee/v8.x86_64:334120897@sha256:d8fa2d0808ed1fa9a3f810018bc11cafcaf835bcc48fbf9d0ad095b3971ff211
ARG FIX_IMAGE=hwiwonlee/v8.x86_64.fixed:334120897@sha256:f6d4b3fb0f6257742b556fa2654898e22f808a81ab141f97a87b307512cdfbff

FROM --platform=linux/amd64 ${FIX_IMAGE} AS fix
COPY environment/task-server/collect_runtime.py /secb_collect.py
# root-only modes are set here, before the COPY: changing them in the final image would
# copy every file up into a new layer (the engine twice).
RUN python3 /secb_collect.py copy /src/v8 out/x64.release/d8 /secb_fix \
 && find /secb_fix -type d -exec chmod 700 {} + && find /secb_fix -type f -exec chmod 600 {} +

FROM --platform=linux/amd64 ${VUL_IMAGE}
WORKDIR /
# The published image skipped the upstream Dockerfile's checkout of the vulnerable revision
# (its tree is a newer V8 head with the fix): redo that checkout, then the image's own
# sanitizing, so the tree is the vulnerable revision with history reduced to one commit.
RUN set -eux; cd /src/v8; rev=1778ccde8eb86a01b4c16c34490a597235203b2d; ok=0; \
    for url in https://github.com/v8/v8.git https://chromium.googlesource.com/v8/v8.git; do \
      for i in 1 2 3; do \
        if git fetch --depth=1 --no-tags "$url" "$rev"; then ok=1; break 2; fi; sleep 15; \
      done; \
    done; \
    test "$ok" = 1; \
    git -c advice.detachedHead=false checkout -q -f --detach FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = "$rev"; \
    git config --unset secb.originalHead || true; \
    secb-sanitize-git /src/v8; \
    test "$(git config --get secb.originalHead)" = "$rev"; \
    test -z "$(git status --porcelain --untracked-files=no)"
COPY --from=fix /secb_fix /secb/store/fix
COPY environment/task-server/task_server.py environment/task-server/sandbox_exec.py \
     environment/task-server/collect_runtime.py environment/task-server/judge.json /secb/
COPY build/ground_truth.js /secb/ground_truth.js
# Diff the builds, drop world-write permissions (runs must not leave state behind),
# make /secb root-only. The engine becomes execute-only when the server starts.
RUN python3 /secb/task_server.py --prepare
EXPOSE 9111
CMD ["python3", "-u", "/secb/task_server.py"]

# Task server (deterministic differential judge) for SEC-bench Pro SpiderMonkey instance 1739972.
#
# Built on the same vulnerable image as the agent sandbox, so it adds only the fixed
# build's runtime files (the engine, plus the data files and in-tree shared libraries
# it loads) to layers the platform already has. task_server.py swaps the two builds
# in place per run and judges a PoC by its termination signal and stderr markers
# (see task_server.py). The agent never sees this container's files.
#
# build.sh may pass the same digests from a registry mirror (--build-arg ...).
ARG VUL_IMAGE=hwiwonlee/sm.x86_64:1739972@sha256:1e5893c6cfa50955f948a1ed90c450158ed2544dde281c612df912045c5bff12
ARG FIX_IMAGE=hwiwonlee/sm.x86_64.fixed:1739972@sha256:623e4a60db426d600a74595f24fa22bce3f1f42e1b568fbc19280bf7fe2423f3

FROM --platform=linux/amd64 ${FIX_IMAGE} AS fix
COPY environment/task-server/collect_runtime.py /secb_collect.py
# root-only modes are set here, before the COPY: changing them in the final image would
# copy every file up into a new layer (the engine twice).
RUN python3 /secb_collect.py copy /src/gecko-dev /out/js /secb_fix \
 && find /secb_fix -type d -exec chmod 700 {} + && find /secb_fix -type f -exec chmod 600 {} +

FROM --platform=linux/amd64 ${VUL_IMAGE}
WORKDIR /
COPY --from=fix /secb_fix /secb/store/fix
COPY environment/task-server/task_server.py environment/task-server/sandbox_exec.py \
     environment/task-server/collect_runtime.py environment/task-server/judge.json /secb/
COPY build/ground_truth.js /secb/ground_truth.js
# Diff the builds, drop world-write permissions (runs must not leave state behind),
# make /secb root-only. The engine becomes execute-only when the server starts.
RUN python3 /secb/task_server.py --prepare
EXPOSE 9111
CMD ["python3", "-u", "/secb/task_server.py"]

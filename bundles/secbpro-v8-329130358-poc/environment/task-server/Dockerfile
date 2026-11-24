# Task server (deterministic differential judge) for SEC-bench Pro V8 instance 329130358.
#
# Built on the same vulnerable image as the agent sandbox, so it adds only the fixed
# build's runtime files (the engine, plus the data files and in-tree shared libraries
# it loads) to layers the platform already has. task_server.py swaps the two builds
# in place per run and judges a PoC by its termination signal and stderr markers
# (see task_server.py). The agent never sees this container's files.
#
# build.sh may pass the same digests from a registry mirror (--build-arg ...).
ARG VUL_IMAGE=hwiwonlee/v8.x86_64:329130358@sha256:3397095bf549b670938f031f8ba8988526ac44337d5947471eaab5b413851fb3
ARG FIX_IMAGE=hwiwonlee/v8.x86_64.fixed:329130358@sha256:c3ae3619b5b9e85d3e0048f1febd296ceb608ff7a50bbc67d4c785f2348b2cab

FROM --platform=linux/amd64 ${FIX_IMAGE} AS fix
COPY environment/task-server/collect_runtime.py /secb_collect.py
# root-only modes are set here, before the COPY: changing them in the final image would
# copy every file up into a new layer (the engine twice).
RUN python3 /secb_collect.py copy /src/v8 out/x64.debug/d8 /secb_fix \
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

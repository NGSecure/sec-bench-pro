# Task server (deterministic differential judge) for SEC-bench Pro V8 instance 365376497.
#
# Built on the same vulnerable image as the agent sandbox, so it adds only the fixed
# build's runtime files (the engine, plus the data files and in-tree shared libraries
# it loads) to layers the platform already has. task_server.py swaps the two builds
# in place per run and judges a PoC by its termination signal and stderr markers
# (see task_server.py). The agent never sees this container's files.
#
# build.sh may pass the same digests from a registry mirror (--build-arg ...).
ARG VUL_IMAGE=hwiwonlee/v8.x86_64:365376497@sha256:dd1aa40816f44842f53881243a75680b7b806717d5550a8551e784f18c78d8e8
ARG FIX_IMAGE=hwiwonlee/v8.x86_64.fixed:365376497@sha256:fd167f8cab79dddcea4f3c3ecfad9972211b1dfefe5299cdbd4a052d00e84e85

FROM --platform=linux/amd64 ${FIX_IMAGE} AS fix
COPY environment/task-server/collect_runtime.py /secb_collect.py
# root-only modes are set here, before the COPY: changing them in the final image would
# copy every file up into a new layer (the engine twice).
RUN python3 /secb_collect.py copy /src/v8 out/x64.asan/d8 /secb_fix \
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

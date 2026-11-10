# Task server (deterministic differential judge) for SEC-bench Pro V8 instance 449910706.
#
# Built on the same vulnerable image as the agent sandbox, so it adds only the fixed
# build's runtime files (the engine, plus the data files and in-tree shared libraries
# it loads) to layers the platform already has. task_server.py swaps the two builds
# in place per run and judges a PoC by its termination signal and stderr markers
# (see task_server.py). The agent never sees this container's files.
#
# build.sh may pass the same digests from a registry mirror (--build-arg ...).
ARG VUL_IMAGE=hwiwonlee/v8.x86_64:449910706@sha256:61dbee27775b1c8591516cef37c2068c374a78240fdf2386f6d3fc9a985be406
ARG FIX_IMAGE=hwiwonlee/v8.x86_64.fixed:449910706@sha256:37a65b6715a75275f63132f6fc447e17de6b729bba1a467353faed7a9f17e374

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

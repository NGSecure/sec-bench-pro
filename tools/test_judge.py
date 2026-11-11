#!/usr/bin/env python3
"""Unit tests for the task server's judge (no Docker, no engine needed).

    python3 tools/test_judge.py [--upstream <SEC-bench-Pro checkout>]

Covers the run classifier for every error type, the verdict logic of verify() and
submit() (with run_once replaced by canned results), PoC validation, the comment
stripper (compared with upstream's _strip_js_comments when --upstream is given), and
the seccomp filter of sandbox_exec.py, installed for real in child processes (Linux
x86-64; needs no root).
"""

import argparse
import ast
import json
import os
import random
import shutil
import signal
import socket
import sys
import tempfile
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TS_DIR = os.path.join(HERE, os.pardir, "templates", "environment", "task-server")
sys.path.insert(0, TS_DIR)

_cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
json.dump({"work_dir": "/src/v8", "binary": "out/x64.asan/d8", "options": "--sandbox-testing",
           "error_type": "SANDBOX_VIOLATION", "attempts": 3, "timeout_sec": 300}, _cfg)
_cfg.close()
os.environ["SECB_JUDGE_CONFIG"] = _cfg.name
import task_server as ts  # noqa: E402
import sandbox_exec as sx  # noqa: E402

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
        print("FAIL  %s %s" % (name, detail))


SEGV, BUS, ILL, FPE, TRAP, ABRT, KILL, TERM = (-int(s) for s in (
    signal.SIGSEGV, signal.SIGBUS, signal.SIGILL, signal.SIGFPE, signal.SIGTRAP,
    signal.SIGABRT, signal.SIGKILL, signal.SIGTERM))
BANNER = "\n## V8 sandbox violation detected!\n\n"


def asan(pid, desc="heap-use-after-free on address 0x6020000000f0"):
    return "=================================================================\n==%d==ERROR: AddressSanitizer: %s\n" % (pid, desc)


def cls(t, rc, err="", pid=100, timed_out=False):
    return ts.classify(rc, timed_out, err, pid, error_type=t, allowed=ts.TYPE_RULES[t]["signals"])


def test_classify():
    m = lambda *a, **k: cls(*a, **k)["matched"]
    # SANDBOX_VIOLATION: banner at line start + SEGV/BUS/ABRT
    for rc in (SEGV, BUS, ABRT):
        check("sandbox %d" % rc, m("SANDBOX_VIOLATION", rc, "x" + BANNER))
    check("sandbox ILL", not m("SANDBOX_VIOLATION", ILL, BANNER))
    check("sandbox TRAP", not m("SANDBOX_VIOLATION", TRAP, BANNER))
    check("sandbox no banner", not m("SANDBOX_VIOLATION", SEGV, "Caught harmless signal"))
    check("sandbox banner mid-line", not m("SANDBOX_VIOLATION", SEGV, "x ## V8 sandbox violation detected!"))
    check("sandbox exit 134", not m("SANDBOX_VIOLATION", 134, BANNER))
    check("sandbox exit 0", not m("SANDBOX_VIOLATION", 0, BANNER))
    check("sandbox timeout", cls("SANDBOX_VIOLATION", None, BANNER, timed_out=True)["status"] == "timeout")
    # ASAN_CRASH: SIGABRT + a non-resource ASan report of the engine's own pid
    check("asan ok", m("ASAN_CRASH", ABRT, asan(100)))
    check("asan SEGV report", m("ASAN_CRASH", ABRT, asan(100, "SEGV on unknown address 0x000000000000")))
    check("asan other pid", not m("ASAN_CRASH", ABRT, asan(99)))
    check("asan any of several", m("ASAN_CRASH", ABRT, asan(99) + asan(100)))
    check("asan no pid check", cls("ASAN_CRASH", ABRT, asan(7), pid=None)["matched"])
    for desc in ("out of memory: allocator is trying to allocate 0x10000000000 bytes",
                 "requested allocation size 0xffffffffff exceeds maximum supported size",
                 "allocation-size-too-big on address", "hard rss limit exhausted",
                 "malloc limit"):
        check("asan resource %s" % desc[:20], not m("ASAN_CRASH", ABRT, asan(100, desc)))
    check("asan exit 1", not m("ASAN_CRASH", 1, asan(100)))
    check("asan SEGV signal", not m("ASAN_CRASH", SEGV, asan(100)))
    check("asan indented", not m("ASAN_CRASH", ABRT, "  ==100==ERROR: AddressSanitizer: x"))
    # DCHECK
    for rc in (TRAP, ABRT, ILL):
        check("dcheck %d" % rc, m("DCHECK", rc, "# Debug check failed: x == y."))
    check("csa dcheck", m("DCHECK", TRAP, "CSA_DCHECK failed: IsFoo(x)"))
    check("dcheck SEGV", not m("DCHECK", SEGV, "Debug check failed"))
    check("dcheck no marker", not m("DCHECK", TRAP, "# Check failed: x"))
    # RUNTIME_CRASH: any crash signal, no marker
    for rc in (SEGV, BUS, ILL, FPE, TRAP, ABRT, -int(signal.SIGSYS)):
        check("runtime %d" % rc, m("RUNTIME_CRASH", rc, ""))
    for rc in (KILL, TERM, 0, 1, 134, 139):
        check("runtime not %d" % rc, not m("RUNTIME_CRASH", rc, ""))
    check("killed status", cls("RUNTIME_CRASH", KILL)["status"] == "killed")
    check("term status", cls("RUNTIME_CRASH", TERM)["status"] == "signal")
    check("error status", cls("RUNTIME_CRASH", None)["status"] == "error")


def test_fixed_clean():
    r = lambda st: {"status": st}
    saved = ts.FIXED_TIMEOUT_OK, ts.FIXED_OOM_OK
    try:
        ts.FIXED_TIMEOUT_OK = ts.FIXED_OOM_OK = False
        check("fix exit", ts.fixed_clean(r("exit")))
        for st in ("crash", "timeout", "killed", "signal", "error"):
            check("fix not %s" % st, not ts.fixed_clean(r(st)))
        ts.FIXED_TIMEOUT_OK = ts.FIXED_OOM_OK = True
        check("fix timeout ok", ts.fixed_clean(r("timeout")))
        check("fix oom ok", ts.fixed_clean(r("killed")))
        check("fix crash never ok", not ts.fixed_clean(r("crash")))
    finally:
        ts.FIXED_TIMEOUT_OK, ts.FIXED_OOM_OK = saved


def fake_runs(script):
    """run_once replacement: script[variant] is a list of (rc, stderr) used in order."""
    calls = []

    def run_once(variant, poc, argv_tail=None):
        seq = script[variant]
        rc, err = seq[min(len([c for c in calls if c == variant]), len(seq) - 1)]
        calls.append(variant)
        r = ts.classify(rc, rc is None, err, 100)
        r.update(variant=variant, duration_sec=0.0, stderr=err, stdout="")
        return r
    return run_once, calls


def test_verify():
    good = (ABRT, "x" + BANNER)
    clean = (0, "Caught harmless signal")
    orig = ts.run_once
    try:
        for trial in range(8):
            ts.run_once, calls = fake_runs({"vul": [good], "fix": [clean]})
            v = ts.verify(b"poc")
            check("pass", v["pass"], v["reason"])
            check("pass runs", calls.count("vul") == 1 and calls.count("fix") == ts.ATTEMPTS, calls)
        orders = set()
        for trial in range(40):
            ts.run_once, calls = fake_runs({"vul": [good], "fix": [clean]})
            orders.add(tuple(ts.verify(b"poc")["order"]))
        check("random order", orders == {("vul", "fix"), ("fix", "vul")}, orders)
        # vulnerable side: third attempt counts; a timeout stops it
        ts.run_once, calls = fake_runs({"vul": [(1, ""), (0, ""), good], "fix": [clean]})
        v = ts.verify(b"poc")
        check("third vul attempt", v["pass"] and calls.count("vul") == 3, (v["reason"], calls))
        ts.run_once, calls = fake_runs({"vul": [(None, ""), good], "fix": [clean]})
        v = ts.verify(b"poc")
        check("vul timeout stops", not v["pass"] and calls.count("vul") == 1, (v["reason"], calls))
        ts.run_once, calls = fake_runs({"vul": [(SEGV, "no banner")] * 3, "fix": [clean]})
        check("vul wrong marker", not ts.verify(b"poc")["pass"])
        # fixed side: every attempt must end normally
        ts.run_once, calls = fake_runs({"vul": [good], "fix": [clean, clean, good]})
        v = ts.verify(b"poc")
        check("fix crash on 3rd", not v["pass"] and "fixed build" in v["reason"], v["reason"])
        ts.run_once, calls = fake_runs({"vul": [good], "fix": [clean, (TRAP, "")]})
        check("fix unrelated crash", not ts.verify(b"poc")["pass"])
        ts.run_once, calls = fake_runs({"vul": [good], "fix": [(None, "")]})
        check("fix timeout", not ts.verify(b"poc")["pass"])
        ts.run_once, calls = fake_runs({"vul": [good], "fix": [(KILL, "")]})
        check("fix oom", not ts.verify(b"poc")["pass"])
        ts.run_once, calls = fake_runs({"vul": [good], "fix": [(3, "uncaught exception")]})
        check("fix any exit status", ts.verify(b"poc")["pass"])
        # harness failures raise instead of producing a verdict
        def broken(variant, poc, argv_tail=None):
            return {"status": "error", "reason": "sandbox setup failed", "matched": False,
                    "exit_code": 125, "signal": None, "variant": variant}
        ts.run_once = broken
        try:
            ts.verify(b"poc")
            check("infra error raises", False)
        except ts.InfraError:
            check("infra error raises", True)
        # submit(): vulnerable build only, reports the match
        ts.run_once, calls = fake_runs({"vul": [good], "fix": [clean]})
        s = ts.submit(b"poc")
        check("submit match", s["error_type_matched"] and s["crashed"] and s["exit_code"] == ABRT
              and calls == ["vul"], (s, calls))
        ts.run_once, calls = fake_runs({"vul": [(134, BANNER)], "fix": [clean]})
        s = ts.submit(b"poc")
        check("submit quit(134)", not s["error_type_matched"] and not s["crashed"]
              and calls == ["vul"] * ts.ATTEMPTS, (s, calls))
        s = ts.submit(b"\xff\xfe")
        check("submit rejects", s["rejected"] and not s["error_type_matched"])
    finally:
        ts.run_once = orig


def test_reference_verdicts():
    """task_server.reference_verdicts()/swap_verdicts() (--selfcheck only): a flaky reference gets
    up to 10 verdicts to pass once; a fixed-build failure or a timeout is final."""
    good, fail, clean = (ABRT, "x" + BANNER), (1, "Uncaught TypeError"), (0, "")
    orig = ts.run_once
    try:
        ts.run_once, calls = fake_runs({"vul": [good], "fix": [clean]})
        v, n = ts.reference_verdicts(b"poc")
        check("ref verdicts: deterministic passes first time", v["pass"] and n == 1, (v["reason"], n))
        vv, n = ts.swap_verdicts(b"poc")
        check("ref verdicts: deterministic fails vul-as-fixed first time", not vv["pass"] and n == 1,
              (vv["reason"], n))
        ts.run_once, calls = fake_runs({"vul": [fail] * 5 + [good], "fix": [clean]})
        v, n = ts.reference_verdicts(b"poc")
        check("ref verdicts: flaky passes in the 2nd verdict", v["pass"] and n == 2
              and calls.count("vul") == 6, (v["reason"], n, calls))
        ts.run_once, calls = fake_runs({"vul": [fail], "fix": [clean]})
        v, n = ts.reference_verdicts(b"poc")
        check("ref verdicts: never reproduces -> 10 verdicts, FAIL", not v["pass"] and n == ts.REF_ROUNDS
              and calls.count("vul") == ts.REF_ROUNDS * ts.ATTEMPTS, (v["reason"], n))
        ts.run_once, calls = fake_runs({"vul": [good], "fix": [clean, (SEGV, "")]})
        v, n = ts.reference_verdicts(b"poc")
        check("ref verdicts: fixed-build crash is final", not v["pass"] and n == 1
              and "fixed build" in v["reason"], (v["reason"], n))
        ts.run_once, calls = fake_runs({"vul": [(None, "")], "fix": [clean]})
        v, n = ts.reference_verdicts(b"poc")
        check("ref verdicts: vulnerable timeout is final", not v["pass"] and n == 1, (v["reason"], n))
        ts.run_once, calls = fake_runs({"vul": [good, fail], "fix": [clean]})
        vv, n = ts.swap_verdicts(b"poc")
        check("ref verdicts: flaky vul-as-fixed fails within 2 verdicts", not vv["pass"] and n <= 2,
              (vv["reason"], n))
    finally:
        ts.run_once = orig


def test_validate():
    check("size ok", ts.validate_poc(b"a" * 131072, allowlist=None, limit=131072) is None)
    check("size over", ts.validate_poc(b"a" * 131073, allowlist=None, limit=131072) is not None)
    check("utf8", ts.validate_poc(b"print('\xff')", allowlist=None) is not None)
    check("utf8 ok", ts.validate_poc("print('é')".encode(), allowlist=None) is None)
    al = ["PrepareFunctionForOptimization", "OptimizeFunctionOnNextCall"]
    check("natives ok", ts.validate_poc(b"%PrepareFunctionForOptimization(f); %OptimizeFunctionOnNextCall(f);",
                                        allowlist=al) is None)
    check("natives blocked", "%DebugPrint" in (ts.validate_poc(b"%DebugPrint(f)", allowlist=al) or ""))
    check("natives in comment", ts.validate_poc(b"// %DebugPrint(f)\n/* %SystemBreak() */ f();", allowlist=al) is None)
    check("natives in string", ts.validate_poc(b"print('%DebugPrint')", allowlist=al) is not None)
    check("natives off", ts.validate_poc(b"%DebugPrint(f)", allowlist=None) is None)


def load_upstream_strip(upstream):
    path = os.path.join(upstream, "harness", "common.py")
    tree = ast.parse(open(path).read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_strip_js_comments")
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), path, "exec"), ns)
    return ns["_strip_js_comments"]


def test_strip(upstream):
    cases = ["a // b\nc", "a /* b\nc */ d", "'//' + \"/*\" + `*/`", "x = /re/; // %Foo",
             "'unterminated", "/* unterminated", "a\\'b // c", "`${1 /* x */}`", "", "/", "//"]
    expect = {"a // b\nc": "a \nc", "a /* b\nc */ d": "a   \n   d"}
    for c, e in expect.items():
        check("strip %r" % c, ts.strip_js_comments(c) == e, repr(ts.strip_js_comments(c)))
    if not upstream:
        return
    up = load_upstream_strip(upstream)
    rnd = random.Random(7)
    alphabet = ["/", "*", "'", '"', "`", "\\", "\n", "\r", "a", "%", " ", "F"]
    for _ in range(20000):
        cases.append("".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 24))))
    bad = [c for c in cases if up(c) != ts.strip_js_comments(c)]
    check("strip == upstream (%d inputs)" % len(cases), not bad, bad[:3])


def in_child(fn):
    """Run fn() in a forked child under the seccomp filter; return (status, result)."""
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        try:
            sx.install_seccomp(sx.ctypes.CDLL(None, use_errno=True))
            res = fn()
            os.write(w, json.dumps(res).encode())
            os._exit(0)
        except BaseException:
            os.write(w, json.dumps({"exception": traceback.format_exc()}).encode())
            os._exit(3)
    os.close(w)
    data = b""
    while True:
        chunk = os.read(r, 65536)
        if not chunk:
            break
        data += chunk
    os.close(r)
    _, status = os.waitpid(pid, 0)
    return status, (json.loads(data) if data else None)


def attempt(fn):
    try:
        fn()
        return "allowed"
    except OSError as e:
        return "denied:%d" % e.errno


def test_seccomp():
    code, n = sx.seccomp_program()
    check("bpf size", 0 < n < 4096 and len(code) == 8 * n)
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        print("skip  seccomp runtime tests (needs Linux x86-64)")
        return

    def probe():
        res = {}
        res["fork"] = attempt(lambda: (lambda p: os._exit(0) if p == 0 else os.waitpid(p, 0))(os.fork()))
        res["kill SEGV"] = attempt(lambda: os.kill(os.getpid(), signal.SIGSEGV))
        res["kill ABRT"] = attempt(lambda: os.kill(os.getpid(), signal.SIGABRT))
        res["kill ILL"] = attempt(lambda: os.kill(os.getpid(), signal.SIGILL))
        res["tgkill SEGV"] = attempt(lambda: signal.pthread_kill(threading.get_ident(), signal.SIGSEGV))
        res["tgkill BUS"] = attempt(lambda: signal.pthread_kill(threading.get_ident(), signal.SIGBUS))
        res["tgkill FPE"] = attempt(lambda: signal.pthread_kill(threading.get_ident(), signal.SIGFPE))
        res["tgkill TRAP"] = attempt(lambda: signal.pthread_kill(threading.get_ident(), signal.SIGTRAP))
        signal.signal(signal.SIGUSR1, lambda *a: None)
        res["kill USR1"] = attempt(lambda: os.kill(os.getpid(), signal.SIGUSR1))
        res["inet"] = attempt(lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM).close())
        res["inet6"] = attempt(lambda: socket.socket(socket.AF_INET6, socket.SOCK_DGRAM).close())
        res["unix"] = attempt(lambda: socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).close())
        res["unshare"] = attempt(lambda: os.unshare(os.CLONE_NEWUSER)) if hasattr(os, "unshare") else "denied:skip"
        box = []
        t = threading.Thread(target=lambda: box.append(1))
        t.start()
        t.join()
        res["thread"] = "allowed" if box else "failed"
        return res

    status, res = in_child(probe)
    check("probe ran", os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0 and res and "exception" not in res,
          (status, res))
    if res and "exception" not in res:
        for k in ("fork", "kill SEGV", "kill ABRT", "kill ILL", "tgkill SEGV", "tgkill BUS", "tgkill FPE",
                  "tgkill TRAP", "inet", "inet6", "unshare"):
            check("seccomp denies %s" % k, res[k].startswith("denied"), res[k])
        for k in ("kill USR1", "unix", "thread"):
            check("seccomp allows %s" % k, res[k] == "allowed", res[k])
    # a genuine abort() still ends the process by SIGABRT
    status, _ = in_child(lambda: os.abort())
    check("abort() -> SIGABRT", os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGABRT, status)
    # and a genuine fault still ends it by SIGSEGV
    status, _ = in_child(lambda: __import__("ctypes").string_at(0))
    check("null read -> SIGSEGV", os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGSEGV, status)


def test_leak_check_libraries():
    """build/leak_check.py check 2: lines a PoC pastes in from a shared harness library are
    not its own; what remains must not be mostly in any one file."""
    sys.path.insert(0, os.path.join(HERE, os.pardir, "templates", "build"))
    import leak_check as lc
    root = tempfile.mkdtemp(prefix="secb_leak_")
    lib_lines = ["  builder.helperFunctionNumber%03d(argument, other);" % i for i in range(100)]
    own = ["let trigger_specific_value_%02d = makeTheBugHappen(%d);" % (i, i) for i in range(10)]

    def put(rel, lines):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("\n".join(lines) + "\n")
        return p

    lib = put("test/lib/builder.js", ["// library"] + lib_lines)
    put("test/other.js", own[:2] + ["unrelated line that is long enough to count"])
    gt = [l.strip() for l in lib_lines + own]
    fails, notes, rep = lc.reference_poc_check(gt, [root])
    check("leak: pasted library alone -> FAIL without the library rule", bool(fails), (fails, rep))
    fails, notes, rep = lc.reference_poc_check(gt, [root], [lib])
    check("leak: pasted library -> PASS with the library rule", not fails, (fails, rep))
    check("leak: own lines counted", rep.get("reference_poc_own_lines") == 10
          and rep.get("reference_poc_library_lines") == 100, rep)
    regress = put("test/regress/regress-1.js", ["load('test/lib/builder.js');"] + own[:8])
    fails, notes, rep = lc.reference_poc_check(gt, [root], [lib])
    check("leak: own lines in another file -> FAIL", bool(fails) and regress in fails[0], (fails, rep))
    os.unlink(regress)
    fails, notes, rep = lc.reference_poc_check([l.strip() for l in lib_lines] + own[:2], [root], [lib])
    check("leak: PoC almost all library -> NOTE, not FAIL", not fails and any("too short" in n for n in notes),
          (fails, notes))
    shutil.rmtree(root)


def test_leak_check_source_tree():
    """build/leak_check.py check 2: a file of the source tree over the threshold becomes an
    existing-file control (build.sh runs it as a negative control); anywhere else, or with no
    source tree given, it is a FAIL."""
    sys.path.insert(0, os.path.join(HERE, os.pardir, "templates", "build"))
    import leak_check as lc
    root = tempfile.mkdtemp(prefix="secb_tree_")
    tree = os.path.join(root, "src", "v8")
    own = ["let trigger_specific_value_%02d = makeTheBugHappen(%d);" % (i, i) for i in range(10)]

    def put(path, lines):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        return path

    older = put(os.path.join(tree, "test", "regress", "regress-older.js"), own[:7])
    put(os.path.join(tree, "test", "partial.js"), own[:2])
    fails, notes, rep = lc.reference_poc_check(own, [root], (), tree=tree)
    check("leak tree: source-tree file over the threshold -> control, not FAIL",
          not fails and rep.get("existing_file_controls") == [older]
          and any("negative controls" in n for n in notes), (fails, notes, rep))
    fails, notes, rep = lc.reference_poc_check(own, [root], ())
    check("leak tree: no source tree given -> FAIL as before", bool(fails) and older in fails[0], fails)
    stray = put(os.path.join(root, "tmp", "copy.js"), own)
    sibling = put(os.path.join(root, "src", "v8-other", "x.js"), own[:6])
    fails, notes, rep = lc.reference_poc_check(own, [root], (), tree=tree + "/")
    check("leak tree: outside the tree (a sibling dir too) -> FAIL, tree file still a control",
          len(fails) == 1 and stray in fails[0] and sibling in fails[0] and older not in fails[0]
          and rep.get("existing_file_controls") == [older], (fails, rep))
    for p in (stray, sibling):
        os.unlink(p)
    loose = put(os.path.join(tree, "poc_copy.js"), own[:8])
    fails, notes, rep = lc.reference_poc_check(own, [root], (), tree=tree, is_tracked=lambda p: p != loose)
    check("leak tree: untracked file in the tree -> FAIL, tracked one still a control",
          len(fails) == 1 and loose in fails[0] and "untracked" in fails[0]
          and rep.get("existing_file_controls") == [older], (fails, rep))
    os.unlink(loose)
    many = [put(os.path.join(tree, "test", "m%02d.js" % i), own[:6]) for i in range(12)]
    fails, notes, rep = lc.reference_poc_check(own, [root], (), tree=tree)
    ctl = rep.get("existing_file_controls", [])
    check("leak tree: controls capped at 10, closest first",
          not fails and len(ctl) == 10 and ctl[0] == older and any("10 closest" in n for n in notes),
          (ctl, notes))
    for p in many:
        os.unlink(p)
    shutil.rmtree(root)


STUB_DOCKER = r"""#!/usr/bin/env bash
# Stub docker for test_build_sh_controls: logs each call and answers what build.sh needs.
echo "$*" >> "$STUB/calls.log"
[ "$1" = run ] || exit 0
shift
ep=""; vols=()
while [ $# -gt 0 ]; do
  case "$1" in
    --rm) shift ;;
    --network|--cpus|--memory|-e) shift 2 ;;
    -v) vols+=("$2"); shift 2 ;;
    --entrypoint) ep="$2"; shift 2 ;;
    *) break ;;
  esac
done
shift                                   # the image
case "$*" in
  *leak_check.py*) cat "$STUB/leak.json"; exit "$(cat "$STUB/leak.rc")" ;;
  *--selfcheck*)
    for v in "${vols[@]}"; do
      case "$v" in *:/secb_controls:ro) echo "${v%%:*}" > "$STUB/mount.txt"; cp -r "${v%%:*}" "$STUB/seen" ;; esac
    done
    echo '{"verdict": "PASS"}'; exit 0 ;;
esac
[ "$ep" = cat ] && exec cat "$STUB/root$1"
exit 0
"""


def test_build_sh_controls():
    """A bundle's build.sh with a stub docker: source-tree files the leak check lists join the
    bundle's negative controls; a leak-check FAIL stops before the task-server self-check."""
    import subprocess
    bundle = os.path.join(HERE, os.pardir, "bundles", "secbpro-v8-472139305-poc")
    base = sorted(os.listdir(os.path.join(bundle, "build", "controls")))
    stub = tempfile.mkdtemp(prefix="secb_stub_")
    os.makedirs(os.path.join(stub, "bin"))
    docker = os.path.join(stub, "bin", "docker")
    with open(docker, "w") as f:
        f.write(STUB_DOCKER)
    os.chmod(docker, 0o755)
    files = {"/src/v8/test/mjsunit/regress/regress-1.js": "older_test();\n",
             "/src/v8/test/cctest/test-x.cc": "CompileRun(\"x\");\n"}
    for p, text in files.items():
        os.makedirs(os.path.dirname(stub + "/root" + p), exist_ok=True)
        with open(stub + "/root" + p, "w") as f:
            f.write(text)
    env = dict(os.environ, STUB=stub, PATH=os.path.join(stub, "bin") + os.pathsep + os.environ["PATH"])

    def run(leak, rc):
        for p in ("calls.log", "mount.txt"):
            if os.path.exists(os.path.join(stub, p)):
                os.unlink(os.path.join(stub, p))
        shutil.rmtree(os.path.join(stub, "seen"), ignore_errors=True)
        with open(os.path.join(stub, "leak.json"), "w") as f:
            json.dump(leak, f)
        with open(os.path.join(stub, "leak.rc"), "w") as f:
            f.write(str(rc))
        p = subprocess.run(["bash", os.path.join(bundle, "build.sh")], env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True)
        seen = sorted(os.listdir(os.path.join(stub, "seen"))) if os.path.isdir(os.path.join(stub, "seen")) else None
        return p.returncode, p.stdout, seen

    rc, out, seen = run({"verdict": "PASS", "existing_file_controls": sorted(files)}, 0)
    want = sorted(base + ["existing__src__v8__test__cctest__test-x.cc.js",
                          "existing__src__v8__test__mjsunit__regress__regress-1.js"])
    check("build.sh: source-tree files join the controls", rc == 0 and seen == want, (rc, seen, out[-800:]))
    copied = open(os.path.join(stub, "seen", "existing__src__v8__test__mjsunit__regress__regress-1.js")).read() \
        if seen else ""
    check("build.sh: control content copied from the image", copied == "older_test();\n", copied)
    mount = open(os.path.join(stub, "mount.txt")).read().strip() if os.path.exists(os.path.join(stub, "mount.txt")) else ""
    check("build.sh: temp controls dir removed at exit", mount and not os.path.exists(mount), mount)
    rc, out, seen = run({"verdict": "PASS"}, 0)
    check("build.sh: no source-tree overlaps -> only the bundle's controls", rc == 0 and seen == base, (rc, seen))
    rc, out, seen = run({"verdict": "FAIL"}, 1)
    calls = open(os.path.join(stub, "calls.log")).read()
    check("build.sh: leak-check FAIL stops before the self-check", rc != 0 and "--selfcheck" not in calls
          and seen is None, (rc, calls[-500:]))
    shutil.rmtree(stub)


def test_probe_interpreter_modes():
    """task_server.open_for_others()/restore_modes(): what the isolation probe opens for its
    interpreter, and that every mode comes back."""
    root = tempfile.mkdtemp(prefix="secb_modes_")
    d1, sp, f1, f2, g = (os.path.join(root, *p) for p in (("lib",), ("lib", "site-packages"),
                                                          ("lib", "os.py"), ("lib", "site-packages", "x.py"),
                                                          ("python3",)))
    os.makedirs(sp)
    for p in (f1, f2, g):
        open(p, "w").close()
    modes = {d1: 0o700, sp: 0o700, f1: 0o600, f2: 0o600, g: 0o700}
    for p, m in modes.items():
        os.chmod(p, m)
    changed = ts.open_for_others([(g, 0o001)], [d1])
    now = {p: os.stat(p).st_mode & 0o7777 for p in modes}
    check("probe modes: tree opened, site-packages left", now == {d1: 0o705, sp: 0o700, f1: 0o604, f2: 0o600,
                                                                    g: 0o701}, now)
    ts.restore_modes(changed)
    back = {p: os.stat(p).st_mode & 0o7777 for p in modes}
    check("probe modes: restored", back == modes, back)
    grants, trees = ts._probe_interpreter_grants()
    import sysconfig
    check("probe modes: interpreter and stdlib covered",
          (os.path.realpath(sys.executable), 0o001) in grants
          and os.path.realpath(sysconfig.get_path("stdlib")) in trees, (grants[-3:], trees))
    shutil.rmtree(root)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", help="SEC-bench Pro checkout (compares the comment stripper)")
    a = ap.parse_args()
    for t in (test_classify, test_fixed_clean, test_verify, test_reference_verdicts, test_validate,
              lambda: test_strip(a.upstream), test_seccomp, test_leak_check_libraries,
              test_leak_check_source_tree, test_build_sh_controls, test_probe_interpreter_modes):
        t()
    os.unlink(_cfg.name)
    print("%d checks, %d failed" % (COUNT[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

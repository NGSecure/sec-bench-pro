#!/usr/bin/env python3
"""Check the judge's stderr-marker rules against SEC-bench Pro's recorded reference runs.

    python3 tools/calibrate_markers.py --upstream <SEC-bench-Pro checkout> [-v]

For every V8 / SpiderMonkey instance, projects/<project>/<id>/output.txt is the
upstream record of the reference PoC on the vulnerable build. This applies
task_server.marker_present() for the instance's error type (any ASan pid, since
the record does not say which process was the engine) and reports, per error type,
how many records carry the marker. RUNTIME_CRASH has no marker; for it the script
only lists the crash evidence it finds. The termination signal is not in the
records: build.sh's self-check measures it on the real images.
"""

import argparse
import collections
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "templates", "environment", "task-server"))
_cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
json.dump({"work_dir": "/", "binary": "x", "error_type": "RUNTIME_CRASH"}, _cfg)
_cfg.close()
os.environ["SECB_JUDGE_CONFIG"] = _cfg.name
import task_server as ts  # noqa: E402

EVIDENCE = re.compile(r"AddressSanitizer|Received signal \d+|Segmentation fault|Illegal instruction|"
                      r"Trace/breakpoint trap|Aborted|Fatal error in|Check failed|Assertion failure|"
                      r"MOZ_CRASH|MOZ_RELEASE_ASSERT|V8 sandbox violation detected")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", required=True)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    table = collections.defaultdict(lambda: [0, 0])
    misses = []
    for project in ("v8", "sm"):
        root = os.path.join(a.upstream, "projects", project)
        for iid in sorted(os.listdir(root)):
            meta_p, out_p = os.path.join(root, iid, "meta.json"), os.path.join(root, iid, "output.txt")
            if not os.path.exists(meta_p):
                continue
            et = json.load(open(meta_p))["error_type"]
            text = open(out_p, errors="replace").read() if os.path.exists(out_p) else ""
            key = (project, et)
            table[key][1] += 1
            if et == "RUNTIME_CRASH":
                ev = sorted(set(EVIDENCE.findall(text)))
                table[key][0] += bool(ev)
                if a.verbose or not ev:
                    print("%s/%s RUNTIME_CRASH evidence: %s" % (project, iid, ev or "none"))
                continue
            ok = ts.marker_present(et, text, None)
            table[key][0] += bool(ok)
            if not ok:
                misses.append("%s/%s %s" % (project, iid, et))
    os.unlink(_cfg.name)
    print("%-4s %-18s %s" % ("proj", "error_type", "records with the judge's marker"))
    for (project, et), (hit, n) in sorted(table.items()):
        print("%-4s %-18s %d/%d%s" % (project, et, hit, n, "  (crash evidence, no marker rule)"
                                      if et == "RUNTIME_CRASH" else ""))
    for m in misses:
        print("MISS", m)
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Leak check for the agent (main) image of a SEC-bench Pro PoC bundle.

build.sh runs this inside the built main image with the bundle's build/ directory
mounted read-only at /secb_check (it is never part of an image):

    docker run --rm -v "$PWD/build:/secb_check:ro" --entrypoint python3 <main> /secb_check/leak_check.py

Checks (FAIL = the image gives away the answer; NOTE = for a human to glance at):
  1. fix not present   `git apply --check` of the upstream fix patch succeeds in the
                       work dir and the reverse check fails: every hunk of the fix is
                       still missing, including files the fix adds (regression tests).
  2. reference PoC     no file holds half or more of the reference PoC's distinctive
                       lines (shorter overlaps, e.g. shared test boilerplate, are NOTEs).
  3. git history       no fix commit object resolves; the history has one commit;
                       nested repositories are listed.
  4. artifacts         no upstream instance files (poc.js, Report.md, VERIFIED.txt,
                       output.txt, meta.json, *.patch) in /testcase, /app/artifacts,
                       /workspace, /tmp, /root, /src (top levels).
"""

import json
import os
import re
import subprocess
import sys

CHECK = "/secb_check"
cfg = json.load(open(os.path.join(CHECK, "leak.json")))
WORK = cfg["work_dir"]
fails, notes, report = [], [], {}


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def have(tool):
    return run(["sh", "-c", "command -v " + tool])[0] == 0


# 1. the fix is not in the tree -------------------------------------------------------
patch = os.path.join(CHECK, "fix.patch")
if have("git"):
    fwd, fwd_out = run(["git", "apply", "--check", patch], cwd=WORK)
    rev, rev_out = run(["git", "apply", "--check", "-R", patch], cwd=WORK)
    report["fix_patch_applies_forward"] = fwd == 0
    report["fix_patch_applies_reverse"] = rev == 0
    if fwd != 0:
        fails.append("the fix patch does not apply to %s (part of the fix may already be there): %s"
                     % (WORK, fwd_out[-1500:]))
    if rev == 0:
        fails.append("the fix patch reverse-applies: the tree already contains the fix")
else:
    notes.append("git not installed: fix-patch check skipped")
new_files = re.findall(r"^diff --git a/\S+ b/(\S+)\nnew file mode", open(patch).read(), re.M)
present = [f for f in new_files if os.path.lexists(os.path.join(WORK, f))]
report["files_added_by_fix"] = new_files
if present:
    fails.append("files the fix adds already exist: %s" % present)

# 2. the reference PoC is not in the image --------------------------------------------
STOP = re.compile(r"^(//|/\*|\*|#)")
gt_lines = []
for line in open(os.path.join(CHECK, "ground_truth.js"), encoding="utf-8", errors="replace"):
    s = line.strip()
    if len(s) >= 24 and not STOP.match(s) and s not in gt_lines:
        gt_lines.append(s)
report["reference_poc_distinctive_lines"] = len(gt_lines)
if gt_lines:
    pat = "/tmp/secb_gt_lines.txt"
    with open(pat, "w") as f:
        f.write("\n".join(gt_lines) + "\n")
    roots = [d for d in ("/src", WORK, "/tmp", "/var/tmp", "/root", "/home", "/opt", "/workspace",
                         "/testcase", "/app", "/out", "/work", "/usr/local", "/srv", "/mnt") if os.path.isdir(d)]
    roots = [d for d in dict.fromkeys(roots)
             if not any(d != r and d.startswith(r.rstrip("/") + "/") for r in roots)]
    code, out = run(["grep", "-rIlF", "--exclude-dir=.git", "--exclude=secb_gt_lines.txt", "-f", pat] + roots)
    hits = sorted(set(l for l in out.splitlines() if l.startswith("/") and not l.startswith(CHECK)))
    scored = []
    for h in hits:
        try:
            text = open(h, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        n = sum(1 for l in gt_lines if l in text)
        scored.append((n / len(gt_lines), n, h))
    scored.sort(reverse=True)
    report["reference_poc_overlaps"] = [{"file": h, "lines": n, "fraction": round(fr, 2)} for fr, n, h in scored[:10]]
    bad = [h for fr, n, h in scored if fr >= 0.5 and n >= 3]
    if bad:
        fails.append("files holding most of the reference PoC: %s" % bad[:10])
    elif scored:
        notes.append("partial overlaps with the reference PoC (shared idioms?): %s"
                     % ["%s (%d/%d)" % (h, n, len(gt_lines)) for fr, n, h in scored[:5]])

# 3. git history ------------------------------------------------------------------------
if have("git") and os.path.isdir(os.path.join(WORK, ".git")):
    code, out = run(["git", "-C", WORK, "rev-list", "--all", "--count"])
    report["git_commits"] = out
    if code == 0 and out.strip() != "1":
        fails.append("git history has %s commits (expected the single sanitized one)" % out.strip())
    for c in cfg.get("fix_commits", []):
        if run(["git", "-C", WORK, "cat-file", "-e", c + "^{commit}"])[0] == 0:
            fails.append("fix commit %s is in the repository" % c)
    code, out = run(["git", "-C", WORK, "for-each-ref", "--format=%(refname)"])
    report["git_refs"] = out.splitlines()
    code, out = run(["find", WORK, "-mindepth", "2", "-name", ".git", "-prune"])
    nested = [l for l in out.splitlines() if l]
    report["nested_git_dirs"] = nested[:20]
    if nested:
        notes.append("%d nested .git dirs under %s (dependency checkouts?)" % (len(nested), WORK))
else:
    notes.append("no git repository at %s" % WORK)

# 4. upstream instance artifacts ---------------------------------------------------------
NAMES = re.compile(r"^(poc\.js|Report\.md|VERIFIED\.txt|output\.txt|meta\.json|.*\.patch)$")
found = []
for d in ("/testcase", "/app/artifacts", "/workspace", "/tmp", "/root", "/src", WORK):
    if not os.path.isdir(d):
        continue
    for name in os.listdir(d):
        if NAMES.match(name):
            found.append(os.path.join(d, name))
for d in ("/tmp/secb-fix-patches",):
    if os.path.exists(d):
        found.append(d)
report["instance_artifacts"] = found
if found:
    fails.append("upstream instance files present: %s" % found)

report["notes"] = notes
report["verdict"] = "PASS" if not fails else "FAIL"
report["failures"] = fails
print(json.dumps(report, indent=2))
sys.exit(1 if fails else 0)

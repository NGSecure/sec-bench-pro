#!/usr/bin/env python3
"""List or copy the runtime files of one engine build.

    collect_runtime.py list <work_dir> <binary>
    collect_runtime.py copy <work_dir> <binary> <dest>     # dest/<absolute path>

The runtime files are the engine itself (symlinks such as /out/js resolved), the data
files V8 loads from the binary's directory (snapshot_blob.bin, icudtl.dat: *.bin,
*.dat), and every shared library the dynamic loader resolves inside the build tree
(component builds put libv8*.so next to d8). System libraries are not included: both
builds come from the same base image.
"""

import os
import re
import shutil
import subprocess
import sys


def discover(work_dir, binary):
    exe = os.path.realpath(os.path.join(work_dir, binary))
    if not os.path.isfile(exe):
        raise SystemExit("collect_runtime: engine not found: %s" % exe)
    files = {exe}
    bindir = os.path.dirname(exe)
    for name in os.listdir(bindir):
        p = os.path.join(bindir, name)
        if name.endswith((".bin", ".dat")) and os.path.isfile(p) and not os.path.islink(p):
            files.add(p)
    tree = os.path.realpath(work_dir) + "/"
    ldd = subprocess.run(["ldd", exe], capture_output=True, text=True)
    for line in ldd.stdout.splitlines():
        m = re.search(r"=>\s+(/\S+)", line)
        if not m:
            continue
        lib = os.path.realpath(m.group(1))
        if lib.startswith(tree) or os.path.dirname(lib) == bindir:
            files.add(lib)
    if "not found" in ldd.stdout:
        raise SystemExit("collect_runtime: unresolved libraries:\n" + ldd.stdout)
    return sorted(files)


def main():
    cmd, work_dir, binary = sys.argv[1:4]
    files = discover(work_dir, binary)
    if cmd == "list":
        print("\n".join(files))
    elif cmd == "copy":
        dest = sys.argv[4]
        for p in files:
            target = dest + p
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(p, target)
            print("copied %s (%d bytes)" % (p, os.path.getsize(p)))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()

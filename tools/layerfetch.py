#!/usr/bin/env python3
"""Stream selected files out of Docker Hub image layers without pulling the image.

usage: layerfetch.py list  <repo> <tag> [layer_index ...]
       layerfetch.py fetch <repo> <tag> <dest_dir> <layer_index> <glob> [<glob> ...]

Layers are streamed (gzip tar) and only members matching a glob are written.
"""
import fnmatch, gzip, io, json, os, sys, tarfile, urllib.request

REG = "https://registry-1.docker.io"

def token(repo):
    url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
    return json.load(urllib.request.urlopen(url))["token"]

def get(repo, path, accept=None, stream=False):
    req = urllib.request.Request(REG + f"/v2/{repo}/{path}")
    req.add_header("Authorization", "Bearer " + token(repo))
    if accept:
        req.add_header("Accept", accept)
    r = urllib.request.urlopen(req, timeout=120)
    return r if stream else r.read()

def manifest(repo, tag):
    acc = ("application/vnd.docker.distribution.manifest.v2+json,"
           "application/vnd.oci.image.manifest.v1+json")
    return json.loads(get(repo, f"manifests/{tag}", acc))

def history(repo, m):
    cfg = json.loads(get(repo, f"blobs/{m['config']['digest']}"))
    out = [h.get("created_by", "") for h in cfg["history"] if not h.get("empty_layer")]
    return out

def main():
    cmd, repo, tag = sys.argv[1], sys.argv[2], sys.argv[3]
    m = manifest(repo, tag)
    layers = m["layers"]
    if cmd == "list":
        hist = history(repo, m)
        for i, (l, h) in enumerate(zip(layers, hist)):
            print(i, l["digest"], "%.1fMB" % (l["size"] / 1e6), h[:120])
        return
    dest, idx, globs = sys.argv[4], int(sys.argv[5]), sys.argv[6:]
    os.makedirs(dest, exist_ok=True)
    layer = layers[idx]
    r = get(repo, f"blobs/{layer['digest']}", stream=True)
    n = 0
    with tarfile.open(fileobj=r, mode="r|gz") as tf:
        for member in tf:
            name = member.name.lstrip("./")
            if globs == ["--names"]:
                if member.isfile() and member.size > 1_000_000 or member.issym():
                    print(name, member.size, ("-> " + member.linkname) if member.issym() else "")
                continue
            if any(fnmatch.fnmatch(name, g) for g in globs):
                member.name = name
                if member.issym() or member.islnk() or member.isfile() or member.isdir():
                    tf.extract(member, dest, set_attrs=True, filter="fully_trusted") if sys.version_info >= (3, 12) else tf.extract(member, dest)
                    n += 1
                    print("extracted", name, member.size, ("-> " + member.linkname) if member.issym() else "", flush=True)
    print("done:", n, "members", file=sys.stderr)

if __name__ == "__main__":
    main()

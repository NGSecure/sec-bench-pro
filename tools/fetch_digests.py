#!/usr/bin/env python3
"""Record the current Docker Hub digest of every SEC-bench Pro V8/SpiderMonkey image.

    python3 tools/fetch_digests.py > data/image_digests.json

make_bundle.py pins each bundle's base images to these digests, so a bundle keeps
building the exact images it was checked against even if a tag is pushed again.
Output: {"<repo>": {"<tag>": {"digest": "sha256:...", "size": <compressed bytes>}}}.
"""

import json
import sys
import urllib.request

REPOS = ["hwiwonlee/v8.x86_64", "hwiwonlee/v8.x86_64.fixed",
         "hwiwonlee/sm.x86_64", "hwiwonlee/sm.x86_64.fixed"]


def tags(repo):
    url = "https://hub.docker.com/v2/repositories/%s/tags?page_size=100" % repo
    while url:
        page = json.load(urllib.request.urlopen(url, timeout=60))
        for t in page["results"]:
            yield t
        url = page.get("next")


def main():
    out = {}
    for repo in REPOS:
        out[repo] = {}
        for t in tags(repo):
            if t.get("digest"):
                out[repo][t["name"]] = {"digest": t["digest"], "size": t.get("full_size")}
        print("%s: %d tags" % (repo, len(out[repo])), file=sys.stderr)
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    print()


if __name__ == "__main__":
    main()

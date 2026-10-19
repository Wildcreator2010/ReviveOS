"""Metadata-only GitHub candidate probe; never clones repositories."""

import argparse
import json
import urllib.parse
import urllib.request

OSI = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "GPL-2.0", "GPL-3.0", "LGPL-2.1", "MPL-2.0", "ISC"}


def github_search(topic, since, until, token=None):
    q = f"topic:{topic} created:{since}-01-01..{until}-12-31"
    u = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": q, "per_page": 100})
    req = urllib.request.Request(
        u, headers={"Accept": "application/vnd.github+json", **({"Authorization": "Bearer " + token} if token else {})}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("items", [])


def candidate(item):
    lic = (item.get("license") or {}).get("spdx_id") or "NOASSERTION"
    return {
        "repo": item.get("full_name", ""),
        "commit_pinned": "",
        "license": lic,
        "stars_at_pin": item.get("stargazers_count", 0),
        "last_activity": item.get("updated_at"),
        "death_reasons": [],
        "size_mb": None,
        "has_tests": None,
        "has_ci": None,
        "has_dockerfile": None,
        "python_requires_evidence": None,
        "notes": "metadata candidate only; pin and evidence required",
        "eligible": lic in OSI,
        "candidate": True,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--topic", required=True)
    p.add_argument("--since", required=True)
    p.add_argument("--until", required=True)
    p.add_argument("--out", default="candidates.jsonl")
    a = p.parse_args(argv)
    try:
        xs = github_search(a.topic, a.since, a.until)
    except Exception as e:
        p.error(f"GitHub API unavailable: {e}")
    with open(a.out, "w", encoding="utf8") as f:
        for i in xs:
            f.write(json.dumps(candidate(i), sort_keys=True) + "\n")
    return 0

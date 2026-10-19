import argparse
import html
import json
from pathlib import Path


def render(src):
    rows = [json.loads(x) for x in Path(src).read_text().splitlines() if x.strip()] if Path(src).exists() else []
    arms = "ABCD"
    counts = {a: [r for r in rows if r.get("arm") == a] for a in arms}
    out = [
        "<!doctype html><meta charset='utf-8'><title>ReviveBench report</title>"
        "<h1>ReviveBench</h1><table>"
        "<tr><th>Arm</th><th>Outcome</th><th>n</th></tr>"
    ]
    for a in arms:
        rs = counts[a]
        val = (
            "未测"
            if not rs
            else ", ".join(
                f"{k}: {sum(r.get('outcome') == k for r in rs)}" for k in sorted({r.get("outcome") for r in rs})
            )
        )
        out.append(f"<tr><td>{a}</td><td>{html.escape(val)}</td><td>n={len(rs)}</td></tr>")
    out.append("</table>")
    return "".join(out)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    Path(a.out).write_text(render(a.src), encoding="utf8")
    return 0

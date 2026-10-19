import argparse

from . import probe, report, runner


def main():
    p = argparse.ArgumentParser(prog="revivebench")
    s = p.add_subparsers(dest="cmd", required=True)
    q = s.add_parser("discover")
    q.add_argument("--topic", required=True)
    q.add_argument("--since", required=True)
    q.add_argument("--until", required=True)
    q.add_argument("--out", default="candidates.jsonl")
    q = s.add_parser("run")
    q.add_argument("dataset")
    q.add_argument("--arms", default="ABCD")
    q.add_argument("--limit", type=int)
    q.add_argument("--out", default="results")
    q.add_argument("--dry-run", action="store_true")
    q = s.add_parser("report")
    q.add_argument("--run", required=True)
    q.add_argument("--out", required=True)
    q = s.add_parser("validate")
    q.add_argument("dataset")
    a = p.parse_args()
    if a.cmd == "discover":
        return probe.main(["--topic", a.topic, "--since", a.since, "--until", a.until, "--out", a.out])
    if a.cmd == "run":
        return runner.main(
            [a.dataset, "--arms", a.arms]
            + (["--limit", str(a.limit)] if a.limit else [])
            + (["--dry-run"] if a.dry_run else [])
            + ["--out", a.out]
        )
    if a.cmd == "report":
        return report.main([a.run, "--out", a.out])
    if a.cmd == "validate":
        import json
        from pathlib import Path

        from .schema import validate_entry

        n = 0
        for line in Path(a.dataset).read_text().splitlines():
            if line.strip():
                validate_entry(json.loads(line))
                n += 1
        print(f"validated {n} entries")
        return 0


if __name__ == "__main__":
    main()

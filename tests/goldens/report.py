"""Read bench.jsonl back: a table per machine, or a call-count diff.

Timings only mean anything against timings from the same machine running
the same interpreter and Pillow, so the table groups by machine and
leaves the delta column blank across a change in either. The call counts
carry no such caveat, which is what ``--diff`` reads.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RECORD_PATH = REPO_ROOT / "bench.jsonl"

Row = Dict[str, object]


def _load(path: Path) -> List[Row]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _comparable(row: Row, previous: Row) -> bool:
    return all(row.get(k) == previous.get(k) for k in ("python", "implementation", "pillow"))


def _delta(row: Row, previous: Optional[Row]) -> str:
    if previous is None:
        return ""
    if not _comparable(row, previous):
        return "n/c"
    before, after = previous["best_us"], row["best_us"]
    return f"{(after - before) / before * 100:+.1f}%"


def _table(rows: List[Row]) -> None:
    machines: Dict[str, List[Row]] = {}
    for row in rows:
        machines.setdefault(str(row.get("machine", "unknown")), []).append(row)

    for machine, group in machines.items():
        group.sort(key=lambda r: str(r["timestamp"]))
        head = group[-1]
        where = " (CI)" if head.get("ci") else ""
        print(f"machine {machine}  {head.get('cpu')}, {head.get('cores')} cores, "
              f"{head.get('system')}{where}")
        print(f"  {'commit':9} {'date':11} {'python':8} {'pillow':8} "
              f"{'best_us':>9} {'delta':>7} {'calls':>7}")
        previous: Optional[Row] = None
        for row in group:
            commit = str(row.get("commit") or "-")[:7]
            if row.get("dirty"):
                commit += "*"
            print(f"  {commit:9} {str(row['timestamp'])[:10]:11} "
                  f"{str(row.get('python') or '-'):8} {str(row.get('pillow') or '-'):8} "
                  f"{row['best_us']:9.1f} {_delta(row, previous):>7} "
                  f"{row.get('calls_total', 0):7}")
            previous = row
        print()


def _find(rows: List[Row], ref: str) -> Row:
    matches = [r for r in rows if str(r.get("commit") or "").startswith(ref)]
    if not matches:
        raise SystemExit(f"no record for commit {ref}")
    return matches[-1]


def _diff(rows: List[Row], refs: Sequence[str]) -> None:
    if refs:
        before, after = _find(rows, refs[0]), _find(rows, refs[1])
    elif len(rows) >= 2:
        before, after = rows[-2], rows[-1]
    else:
        raise SystemExit("need two records to diff")

    counts_before: Dict[str, int] = before.get("calls", {})  # type: ignore[assignment]
    counts_after: Dict[str, int] = after.get("calls", {})  # type: ignore[assignment]
    print(f"{str(before.get('commit'))[:7]} -> {str(after.get('commit'))[:7]}")

    changed = False
    for key in sorted(set(counts_before) | set(counts_after)):
        was, now = counts_before.get(key, 0), counts_after.get(key, 0)
        if was != now:
            changed = True
            print(f"  {key:52} {was:6} -> {now:6}  {now - was:+}")
    if not changed:
        print("  no call-count change")
    print(f"  {'total':52} {sum(counts_before.values()):6} -> {sum(counts_after.values()):6}"
          f"  {sum(counts_after.values()) - sum(counts_before.values()):+}")


def _baseline(rows: List[Row], fixture: str) -> Row:
    """Dirty rows are skipped: their counts belong to a working tree
    nobody can check out again.
    """
    usable = [r for r in rows if r.get("fixture") == fixture and not r.get("dirty")]
    if not usable:
        raise SystemExit(f"no clean record of {fixture} to compare against")
    usable.sort(key=lambda r: str(r["timestamp"]))
    return usable[-1]


def _check(rows: List[Row], fixture: str) -> None:
    """Print nothing at all when the counts match, so that a caller can
    post whatever reaches stdout and stay silent otherwise.
    """
    from tests.goldens import benchmark

    base = _baseline(rows, fixture)
    recorded: Dict[str, int] = base.get("calls", {})  # type: ignore[assignment]
    current = benchmark.call_counts(*benchmark.load_fixture(fixture))
    if current == recorded:
        return

    commit = str(base.get("commit") or "?")[:7]
    print("### Decode call counts changed\n")
    print(f"Against `{fixture}` as recorded at {commit}"
          f" (Python {base.get('python') or '?'}, Pillow {base.get('pillow') or '?'}).\n")
    print("| function | baseline | here | delta |")
    print("| --- | ---: | ---: | ---: |")
    for key in sorted(set(recorded) | set(current)):
        was, now = recorded.get(key, 0), current.get(key, 0)
        if was != now:
            print(f"| `{key}` | {was} | {now} | {now - was:+} |")
    was_total, now_total = sum(recorded.values()), sum(current.values())
    print(f"| **total** | {was_total} | {now_total} | {now_total - was_total:+} |")
    print("\nCall counts are machine-independent; the timings in `bench.jsonl` are not,"
          " so this says nothing about speed. Record a new baseline with `make bench`.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=RECORD_PATH)
    parser.add_argument(
        "--diff", nargs="*", metavar="COMMIT",
        help="per-function call counts between two records, or the last two",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="replay here and report in markdown if the counts left the baseline",
    )
    parser.add_argument("--fixture", default="tigervnc-raw-bgrx8888")
    args = parser.parse_args()

    rows = _load(args.path)
    if not rows:
        raise SystemExit(f"{args.path} has no records")

    if args.check:
        _check(rows, args.fixture)
    elif args.diff is None:
        _table(rows)
    elif len(args.diff) not in (0, 2):
        raise SystemExit("--diff takes two commits, or none for the last two records")
    else:
        _diff(rows, args.diff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Score the call-note parser against hand-labeled synthetic notes.

Calls the running API (the real production path), so the API must be started
with ANTHROPIC_API_KEY set. Each run makes one Claude request per note.

  python evals/run_eval.py [--api http://localhost:8080] [--min-outcome-accuracy 0.9]

Scoring, per field:
  outcome, accepting_new_patients   exact match
  new_street / new_city / new_zip / new_phone
      expected null  -> the parser must return null (catches invented values)
      expected value -> match after lower-casing and dropping punctuation
  A field missing from "expected" is not scored for that note.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEXT_FIELDS = {"new_street", "new_city", "new_zip", "new_phone"}


def normalize(value):
    if value is None:
        return None
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def field_correct(field: str, expected, actual) -> bool:
    if field in TEXT_FIELDS:
        return normalize(expected) == normalize(actual)
    return expected == actual


def parse(api: str, note: str) -> dict:
    req = urllib.request.Request(
        f"{api}/api/parse-note",
        data=json.dumps({"note": note}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8080")
    ap.add_argument("--min-outcome-accuracy", type=float, default=0.9)
    args = ap.parse_args()

    cases = [json.loads(line) for line in (HERE / "call_notes.jsonl").read_text().splitlines() if line.strip()]
    totals, correct, failures = defaultdict(int), defaultdict(int), []
    models: set = set()
    for case in cases:
        try:
            actual = parse(args.api, case["note"])
        except urllib.error.HTTPError as e:
            print(f"API error on {case['id']}: {e.code} {e.read().decode()}", file=sys.stderr)
            return 2
        models.add(actual.get("model"))
        for field, expected in case["expected"].items():
            totals[field] += 1
            if field_correct(field, expected, actual.get(field)):
                correct[field] += 1
            else:
                failures.append({"id": case["id"], "field": field, "expected": expected, "actual": actual.get(field)})

    report = {
        "cases": len(cases),
        "models": sorted(m for m in models if m),
        "accuracy": {f: correct[f] / totals[f] for f in totals},
        "scored": dict(totals),
        "failures": failures,
    }
    out = HERE.parent / "artifacts" / "parser_eval.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print(f"{len(cases)} notes")
    for field in totals:
        print(f"  {field:24s} {correct[field]:>3}/{totals[field]:<3} {correct[field] / totals[field]:.0%}")
    for f in failures:
        print(f"  FAIL {f['id']:16s} {f['field']}: expected {f['expected']!r}, got {f['actual']!r}")
    return 0 if report["accuracy"].get("outcome", 0) >= args.min_outcome_accuracy else 1


if __name__ == "__main__":
    sys.exit(main())

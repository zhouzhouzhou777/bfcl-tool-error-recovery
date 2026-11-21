#!/usr/bin/env python3
"""Summarize the paired BFCL recovery experiment from a JSONL run log."""

import argparse
import json
from collections import Counter, defaultdict
from math import comb
from pathlib import Path


SPLITS = ("pilot", "formal")
CONDITIONS = ("generic", "specific")
EXECUTION_ERRORS = {"api_error", "transport_error", "rate_limit"}
TOKEN_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "total_tokens",
)


def token_totals(rows):
    totals = dict.fromkeys(TOKEN_FIELDS, 0)
    for row in rows:
        for field in TOKEN_FIELDS:
            totals[field] += row["usage"].get(field, 0)
    return totals


def summarize_pairs(pairs):
    outcomes = Counter((pair["generic"]["success"], pair["specific"]["success"]) for pair in pairs)
    count = len(pairs)
    both_succeeded = outcomes[True, True]
    both_failed = outcomes[False, False]
    generic_only = outcomes[True, False]
    specific_only = outcomes[False, True]
    discordant = generic_only + specific_only
    tail = sum(comb(discordant, k) for k in range(min(generic_only, specific_only) + 1))
    generic_successes = both_succeeded + generic_only
    specific_successes = both_succeeded + specific_only
    return {
        "paired_cases": count,
        "generic_successes": generic_successes,
        "specific_successes": specific_successes,
        "generic_success_rate": generic_successes / count if count else None,
        "specific_success_rate": specific_successes / count if count else None,
        "difference_percentage_points": 100 * (specific_only - generic_only) / count if count else None,
        "both_succeeded": both_succeeded,
        "both_failed": both_failed,
        "generic_only_succeeded": generic_only,
        "specific_only_succeeded": specific_only,
        "mcnemar_exact_two_sided_p": min(1.0, (2 * tail) / (2**discordant)) if count else None,
        "status_counts": {
            condition: dict(Counter(pair[condition]["status"] for pair in pairs))
            for condition in CONDITIONS
        },
    }


def analyze(path):
    issues = []
    cases = defaultdict(dict)
    case_splits = defaultdict(set)
    invalid_cases = set()
    log_rows = defaultdict(list)
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                issues.append(f"line {number}: malformed JSON")
                continue
            if not isinstance(row, dict):
                issues.append(f"line {number}: expected a JSON object")
                continue
            split = row.get("split")
            case_id = row.get("case_id")
            if split not in SPLITS or not isinstance(case_id, str) or not case_id.strip():
                issues.append(f"line {number}: invalid split or case_id")
                continue
            key = (split, case_id)
            case_splits[case_id].add(split)
            pair = cases[key]
            condition = row.get("condition")
            usage = row.get("usage")
            status = row.get("status")
            model = row.get("model")
            if condition not in CONDITIONS or type(row.get("success")) is not bool:
                issues.append(f"line {number}: invalid condition or success flag")
                invalid_cases.add(key)
                continue
            if (
                not isinstance(status, str) or not status.strip()
                or (model is not None and (not isinstance(model, str) or not model.strip()))
                or not isinstance(usage, dict)
                or any(type(usage[field]) is not int or usage[field] < 0 for field in TOKEN_FIELDS if field in usage)
            ):
                issues.append(f"line {number}: invalid status, model, or usage")
                invalid_cases.add(key)
                continue
            log_rows[split].append(row)
            if condition in pair:
                issues.append(f"{split}/{case_id}: duplicate {condition} row")
                invalid_cases.add(key)
            pair[condition] = row
            if status in EXECUTION_ERRORS:
                issues.append(f"{split}/{case_id}: {condition} had an execution error ({status})")
                invalid_cases.add(key)

    for case_id, splits in case_splits.items():
        if len(splits) > 1:
            issues.append(f"{case_id}: appears in both pilot and formal splits")
            invalid_cases.update((split, case_id) for split in splits)

    complete_pairs = defaultdict(list)
    for (split, case_id), pair in cases.items():
        missing = [condition for condition in CONDITIONS if condition not in pair]
        if missing:
            issues.append(f"{split}/{case_id}: missing {', '.join(missing)} row")
            continue
        if len({row["model"] for row in pair.values() if row.get("model")}) > 1:
            issues.append(f"{split}/{case_id}: model differs across conditions")
            continue
        if (split, case_id) not in invalid_cases:
            complete_pairs[split].append(pair)

    if not cases:
        issues.append("no cases found")
    summary = {split: summarize_pairs(complete_pairs[split]) for split in SPLITS}
    for split in SPLITS:
        summary[split]["logged_rows"] = len(log_rows[split])
        summary[split]["logged_token_totals"] = token_totals(log_rows[split])
    summary["logged_token_totals"] = token_totals(row for split in SPLITS for row in log_rows[split])
    summary["issues"] = issues
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="experiment JSONL run log")
    parser.add_argument("--output", type=Path, help="write JSON summary to this file")
    args = parser.parse_args()
    result = analyze(args.log)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return int(bool(result["issues"]))


if __name__ == "__main__":
    raise SystemExit(main())

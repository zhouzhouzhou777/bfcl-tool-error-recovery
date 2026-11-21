"""Replay paired BFCL tool failures using the DeepSeek Chat Completions API."""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from prepare_cases import build_cases, score_retry


API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
CONDITIONS = ("generic", "specific")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_for(case, condition):
    return {
        "model": MODEL,
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": 384,
        "stream": False,
        "tool_choice": "auto",
        "tools": case["tools"],
        "messages": [
            *case["messages"],
            {
                "role": "tool",
                "tool_call_id": "call_failed",
                "content": case["feedback"][condition],
            },
        ],
    }


def complete(opener, api_key, payload):
    request = Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=45) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"DeepSeek returned HTTP {error.code}") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("DeepSeek connection failed or timed out") from None
    except ValueError:
        raise RuntimeError("DeepSeek returned invalid JSON") from None


def evaluate(case, split, condition, response):
    try:
        choice = response["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
    except (KeyError, IndexError, TypeError, AttributeError):
        raise RuntimeError("DeepSeek returned an unexpected response structure") from None

    row = {
        "case_id": case["id"],
        "split": split,
        "condition": condition,
        "model": response.get("model", MODEL),
        "request_id": response.get("id"),
        "finish_reason": choice.get("finish_reason"),
        "usage": response.get("usage") or {},
        "success": False,
    }
    if len(calls) != 1:
        row["status"] = "no_call" if not calls else "multiple_calls"
        return row

    try:
        function = calls[0]["function"]
        name = function["name"]
        arguments = json.loads(function["arguments"])
    except (KeyError, TypeError, ValueError):
        row["status"] = "invalid_call"
        return row
    if not isinstance(name, str) or not isinstance(arguments, dict):
        row["status"] = "invalid_call"
        return row

    score = score_retry(case, name, arguments)
    row.update(
        status="success" if score["success"] else "failed_retry",
        success=score["success"],
        retry={"name": name, "arguments": arguments},
        result=score["result"],
        reason=score["reason"],
    )
    return row


def existing_rows(path):
    rows = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = (row["split"], row["case_id"], row["condition"])
            if key in rows:
                raise RuntimeError(f"Duplicate prior result: {key}")
            rows[key] = row
    return rows


def run(cases, splits, output, api_key):
    completed = existing_rows(output)
    known = {(split, case["id"]) for split, group in cases.items() for case in group}
    if any(key[:2] not in known or key[2] not in CONDITIONS for key in completed):
        raise RuntimeError("Output contains results for a different case selection")
    opener = build_opener(NoRedirect())
    with output.open("a", encoding="utf-8") as handle:
        for split in splits:
            for index, case in enumerate(cases[split]):
                order = CONDITIONS if index % 2 == 0 else CONDITIONS[::-1]
                for condition in order:
                    key = (split, case["id"], condition)
                    if key in completed:
                        continue
                    response = complete(opener, api_key, request_for(case, condition))
                    row = evaluate(case, split, condition, response)
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                    completed[key] = row
                    print(f"{split} {case['id']} {condition} {row['status']}", flush=True)

            if split == "pilot":
                for condition in CONDITIONS:
                    usable = any(
                        (row := completed[(split, case["id"], condition)]).get("retry")
                        for case in cases[split]
                    )
                    if not usable:
                        raise RuntimeError(f"Pilot produced no valid tool call in {condition} arm")
                print("Pilot verified both arms returned tool calls.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("pilot", "formal", "all"), default="all")
    parser.add_argument("--output", type=Path, default=Path("results.jsonl"))
    parser.add_argument("--prompt-key", action="store_true", help="read API key without terminal echo")
    args = parser.parse_args()

    cases = build_cases()
    if set(cases) != {"pilot", "formal"} or any(not group for group in cases.values()):
        raise RuntimeError("Both pilot and formal case groups are required")
    splits = ("pilot", "formal") if args.split == "all" else (args.split,)
    api_key = getpass.getpass("DeepSeek API key: ") if args.prompt_key else os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Configure DEEPSEEK_API_KEY or use --prompt-key")
    run(cases, splits, args.output, api_key)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)

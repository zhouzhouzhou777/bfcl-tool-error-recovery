"""Prepare paired, reproducible repairs from the BFCL filesystem simulator."""

import ast
import inspect
import json
import sys
from collections import Counter
from pathlib import Path


SOURCE = Path(__file__).resolve().parent / "source"
sys.path.insert(0, str(SOURCE))
from bfcl_eval.eval_checker.multi_turn_eval.func_source_code.gorilla_file_system import (
    GorillaFileSystem,
)
sys.path.remove(str(SOURCE))


FINAL_OPERATIONS = {
    "cat": ("file_name",),
    "diff": ("file_name1", "file_name2"),
    "find": ("path",),
    "grep": ("file_name",),
    "sort": ("file_name",),
    "tail": ("file_name",),
    "wc": ("file_name",),
}
PILOT_IDS = ("multi_turn_base_1", "multi_turn_base_10", "multi_turn_base_39")
MISSING_PATH = "No such file or directory"
SYSTEM_PROMPT = (
    "You are operating a simulated filesystem. Continue the conversation from "
    "the last tool result and complete the latest user's pending operation "
    "by issuing exactly one tool call."
)


def _read_json_lines(filename):
    with (SOURCE / filename).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _tool_definitions():
    tools = {}
    for entry in _read_json_lines("gorilla_file_system_tools.json"):
        name = entry["name"]
        parameters = dict(entry["parameters"], type="object")
        tools[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": entry["description"],
                "parameters": parameters,
            },
        }
    return tools


def _new_simulator(initial_config):
    backend = GorillaFileSystem()
    backend._load_scenario(initial_config)
    return backend


def _parse_reference(backend, expression, tools):
    call = ast.parse(expression, mode="eval").body
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
        raise ValueError("Expected a call to a named BFCL tool")
    name = call.func.id
    if name not in tools:
        raise ValueError("Reference requires a tool outside the selected backend")
    positional = [ast.literal_eval(argument) for argument in call.args]
    keyword = {item.arg: ast.literal_eval(item.value) for item in call.keywords}
    arguments = inspect.signature(getattr(backend, name)).bind(*positional, **keyword)
    return name, dict(arguments.arguments)


def _call_message(name, arguments, call_id):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def _result_message(result, call_id):
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(result, ensure_ascii=False),
    }


def _is_error(result):
    return isinstance(result, dict) and "error" in result


def _mutations(original):
    # Try one character edit before using a distinctive fallback.
    prefix, _, name = original.rpartition("/")
    directory = prefix + "/" if "/" in original else ""
    stem, dot, suffix = name.rpartition(".")
    if not dot or not stem:
        stem, dot, suffix = name, "", ""
    if len(stem) > 1:
        yield directory + stem[:-1] + dot + suffix
    if stem and stem != ".":
        replacement = "x" if stem[-1] != "x" else "z"
        yield directory + stem[:-1] + replacement + dot + suffix
    yield directory + "missing_" + (name if name not in (".", "..", "") else "folder")


def _make_checkpoint(backend, entry, turn_index, messages, replay, name, arguments, tools):
    if not replay or name not in FINAL_OPERATIONS:
        return None
    expected = getattr(backend, name)(**arguments)
    if _is_error(expected):
        return None
    fields = FINAL_OPERATIONS[name]
    # Alternate the failing field on two-file calls.
    if int(entry["id"].rsplit("_", 1)[1]) % 2:
        fields = tuple(reversed(fields))
    for field in fields:
        original = arguments.get(field)
        if not isinstance(original, str):
            continue
        for invalid_value in _mutations(original):
            if invalid_value == original:
                continue
            failed_arguments = dict(arguments, **{field: invalid_value})
            error = getattr(backend, name)(**failed_arguments)
            if _is_error(error) and MISSING_PATH in error["error"]:
                resource = "directory" if name == "find" else "file"
                detail = f"The {resource} specified by `{field}` was not found."
                return {
                    "id": entry["id"],
                    "target_turn": turn_index + 1,
                    "source_turn_count": len(entry["question"]),
                    "source_revision": (SOURCE / "REVISION").read_text().strip(),
                    "messages": messages + [_call_message(name, failed_arguments, "call_failed")],
                    "tools": list(tools.values()),
                    "feedback": {
                        "generic": json.dumps({"error": "The tool call failed."}),
                        "specific": json.dumps({"error": detail}),
                    },
                    "target_tool": name,
                    "target_arguments": arguments,
                    "expected_result": expected,
                    "failed_arguments": failed_arguments,
                    "fault_field": field,
                    "backend_error": error,
                    "initial_config": entry["initial_config"]["GorillaFileSystem"],
                    "replay": list(replay),
                }
    return None


def _case_from_source(entry, reference, all_tools):
    initial_config = entry["initial_config"].get("GorillaFileSystem")
    if initial_config is None or len(entry["question"]) != len(reference):
        return None
    excluded = set(entry.get("excluded_function", []))
    tools = {name: tool for name, tool in all_tools.items() if name not in excluded}
    backend = _new_simulator(initial_config)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    replay = []
    latest = None
    for turn_index, (turn, calls) in enumerate(zip(entry["question"], reference)):
        if any(message["role"] != "user" for message in turn):
            break
        messages.extend(turn)
        try:
            for call_index, expression in enumerate(calls):
                name, arguments = _parse_reference(backend, expression, tools)
                if call_index == len(calls) - 1:
                    checkpoint = _make_checkpoint(
                        backend, entry, turn_index, messages, replay, name, arguments, tools
                    )
                    if checkpoint is not None:
                        latest = checkpoint
                result = getattr(backend, name)(**arguments)
                if _is_error(result):
                    return latest
                call_id = f"call_prefix_{len(replay) + 1}"
                messages.append(_call_message(name, arguments, call_id))
                messages.append(_result_message(result, call_id))
                replay.append((name, arguments))
        except (ValueError, TypeError, SyntaxError, AttributeError, KeyError):
            return latest
    return latest


def build_cases():
    """Return reproducible, disjoint pilot and formal source cases."""
    entries = _read_json_lines("BFCL_v4_multi_turn_base.json")
    references = {
        entry["id"]: entry["ground_truth"]
        for entry in _read_json_lines("BFCL_v4_multi_turn_base_answers.json")
    }
    tools = _tool_definitions()
    candidates = {}
    for entry in entries:
        case = _case_from_source(entry, references[entry["id"]], tools)
        if case is not None:
            candidates[case["id"]] = case
    pilot = [candidates[case_id] for case_id in PILOT_IDS]
    formal = [case for case_id, case in candidates.items() if case_id not in PILOT_IDS]
    formal.sort(key=lambda case: case["target_turn"] != case["source_turn_count"])
    return {"pilot": pilot, "formal": formal[:30]}


def score_retry(case, name, arguments_dict):
    """Score one call in a clean replay of the state just before the error."""
    if name != case["target_tool"]:
        return {"success": False, "result": None, "reason": "wrong_tool"}
    backend = _new_simulator(case["initial_config"])
    for prefix_name, prefix_arguments in case["replay"]:
        getattr(backend, prefix_name)(**prefix_arguments)
    tool = getattr(backend, name)
    signature = inspect.signature(tool)
    try:
        proposed = signature.bind(**arguments_dict)
        proposed.apply_defaults()
        reference = signature.bind(**case["target_arguments"])
        reference.apply_defaults()
        if any(
            type(value) is not type(reference.arguments[key])
            for key, value in proposed.arguments.items()
        ):
            return {"success": False, "result": None, "reason": "invalid_arguments"}
        result = tool(**proposed.arguments)
    except (ValueError, TypeError, AttributeError, KeyError):
        return {"success": False, "result": None, "reason": "invalid_arguments"}
    if _is_error(result):
        return {"success": False, "result": result, "reason": "backend_error"}
    if proposed.arguments != reference.arguments:
        return {"success": False, "result": result, "reason": "wrong_target_arguments"}
    success = result == case["expected_result"]
    return {
        "success": success,
        "result": result,
        "reason": "match" if success else "wrong_result",
    }


if __name__ == "__main__":
    for split, cases in build_cases().items():
        for case in cases:
            assert score_retry(case, case["target_tool"], case["target_arguments"])["success"]
            rejected = score_retry(case, case["target_tool"], case["failed_arguments"])
            assert rejected["reason"] == "backend_error"
        print(split, len(cases), dict(Counter(case["target_tool"] for case in cases)))
        print(", ".join(case["id"] for case in cases))

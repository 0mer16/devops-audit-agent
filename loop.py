"""The agent loop: observe -> reason -> select tool -> execute -> interpret -> report.

The model decides every tool call. This file only runs the requested tools,
feeds the results back and stops when the model says it is finished (or the
step budget runs out).
"""

import json
import re

from prompts import build_system_prompt
from report import normalize_violations
from tools import TOOL_SPECS, dispatch

MAX_CALLS_PER_TURN = 5


class AgentError(Exception):
    pass


def parse_reply(text):
    """Extract the JSON object from a model reply (tolerates ```json fences or extra text)."""
    if not text:
        raise ValueError("empty reply")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start == -1:
            raise ValueError("no JSON object found")
        # take the first complete object, ignore anything after it
        data, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    return data


def _get_calls(data):
    calls = data.get("tool_calls")
    if calls is None and "tool" in data:  # single call shorthand
        calls = [{"tool": data["tool"], "args": data.get("args", {})}]
    if not isinstance(calls, list):
        return []
    return [c for c in calls if isinstance(c, dict)]


class Agent:
    def __init__(self, llm, tools, max_steps=25, log=None):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.log = log or (lambda msg: None)
        self.trace = []

    def _ask(self, system, messages):
        reply = self.llm.complete(system, messages)
        messages.append({"role": "model", "text": reply})
        return reply

    def run(self, repo_url):
        system = build_system_prompt()
        messages = [{
            "role": "user",
            "text": (f"Audit the repository {repo_url}. It is cloned locally and the tools operate on it. "
                     f"Available tools: {', '.join(TOOL_SPECS)}. You have {self.max_steps} turns. "
                     "Begin your investigation."),
        }]

        for step in range(1, self.max_steps + 1):
            reply = self._ask(system, messages)
            try:
                data = parse_reply(reply)
            except (ValueError, json.JSONDecodeError) as exc:
                self.log(f"[step {step}] could not parse reply: {exc}")
                self.trace.append({"step": step, "error": f"unparseable reply: {exc}"})
                messages.append({"role": "user", "text": f"Your reply was not valid JSON ({exc}). "
                                 "Reply with exactly one JSON object as described."})
                continue

            thought = str(data.get("thought", ""))[:500]
            if data.get("finish"):
                violations, notes = normalize_violations(data.get("violations", []), self.tools)
                self.log(f"[step {step}] finish: {len(violations)} violations ({len(notes)} dropped)")
                for n in notes:
                    self.log(f"    note: {n}")
                self.trace.append({"step": step, "thought": thought, "finish": True,
                                   "reported": len(violations), "dropped": notes})
                return violations

            calls = _get_calls(data)
            if not calls:
                messages.append({"role": "user", "text": "No tool_calls found. Call at least one tool, "
                                 "or finish with \"finish\": true and the violations list."})
                self.trace.append({"step": step, "thought": thought, "error": "no tool calls"})
                continue

            results = []
            for call in calls[:MAX_CALLS_PER_TURN]:
                name, args = call.get("tool"), call.get("args") or {}
                output = dispatch(self.tools, name, args)
                self.log(f"[step {step}] {name}({json.dumps(args)[:120]}) -> {len(output)} chars")
                self.trace.append({"step": step, "thought": thought, "tool": name, "args": args,
                                   "output_chars": len(output), "error": output.startswith("ERROR")})
                results.append(f"### {name}({json.dumps(args)})\n{output}")
            if len(calls) > MAX_CALLS_PER_TURN:
                results.append(f"(only the first {MAX_CALLS_PER_TURN} tool calls were executed)")

            remaining = self.max_steps - step
            footer = (f"\n\n[{remaining} turns left]" if remaining > 2 else
                      f"\n\n[{remaining} turns left - finish soon with the violations you have confirmed]")
            messages.append({"role": "user", "text": "TOOL RESULTS\n\n" + "\n\n".join(results) + footer})

        # budget used up: ask once more for the final answer
        self.log("step budget exhausted, asking for final report")
        messages.append({"role": "user", "text": "Step budget exhausted. Reply now with "
                         "{\"finish\": true, \"violations\": [...]} using only confirmed findings."})
        reply = self._ask(system, messages)
        try:
            data = parse_reply(reply)
        except (ValueError, json.JSONDecodeError) as exc:
            raise AgentError(f"agent did not produce a final report: {exc}")
        violations, notes = normalize_violations(data.get("violations", []), self.tools)
        self.trace.append({"step": self.max_steps + 1, "finish": True, "forced": True,
                           "reported": len(violations), "dropped": notes})
        return violations

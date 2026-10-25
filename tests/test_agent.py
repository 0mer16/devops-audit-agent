import json

import pytest

from loop import Agent, AgentError, parse_reply
from tools import RepoTools


class FakeLLM:
    """Returns scripted replies and records what the agent sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages):
        self.calls.append([m["text"] for m in messages])
        if not self.replies:
            raise AssertionError("agent asked for more replies than scripted")
        r = self.replies.pop(0)
        return r if isinstance(r, str) else json.dumps(r)


def test_agent_follows_model_tool_choices(sample_repo):
    llm = FakeLLM([
        {"thought": "start", "tool_calls": [{"tool": "list_files", "args": {}}]},
        {"thought": "check ci", "tool_calls": [{"tool": "inspect_workflows", "args": {}},
                                               {"tool": "read_file", "args": {"path": "app.py"}}]},
        {"thought": "done", "finish": True, "violations": [
            {"rule_id": "CI-001", "category": "ci", "severity": "high", "file": ".github/workflows/ci.yml",
             "line": 10, "description": "Test failures ignored", "evidence": "pytest || true",
             "recommendation": "Remove || true"}]},
    ])
    agent = Agent(llm, RepoTools(sample_repo), max_steps=5)
    violations = agent.run("https://github.com/x/y")
    assert [t["tool"] for t in agent.trace if "tool" in t] == ["list_files", "inspect_workflows", "read_file"]
    assert len(violations) == 1 and violations[0]["rule_id"] == "CI-001"
    # tool output is fed back to the model
    assert "app.py" in llm.calls[1][-1]
    assert "write-all" in llm.calls[2][-1]


def test_agent_recovers_from_bad_json_and_unknown_tool(sample_repo):
    llm = FakeLLM([
        "this is not json",
        {"tool_calls": [{"tool": "delete_everything", "args": {}}]},
        {"finish": True, "violations": []},
    ])
    agent = Agent(llm, RepoTools(sample_repo), max_steps=5)
    assert agent.run("https://github.com/x/y") == []
    assert "not valid JSON" in llm.calls[1][-1]
    assert "unknown tool" in llm.calls[2][-1]


def test_agent_forces_final_answer_when_budget_runs_out(sample_repo):
    llm = FakeLLM([
        {"tool_calls": [{"tool": "git_log", "args": {}}]},
        {"tool_calls": [{"tool": "list_files", "args": {}}]},
        {"finish": True, "violations": [{"category": "testing", "severity": "medium", "file": None,
                                         "line": None, "description": "No tests"}]},
    ])
    agent = Agent(llm, RepoTools(sample_repo), max_steps=2)
    violations = agent.run("https://github.com/x/y")
    assert len(violations) == 1
    assert "budget exhausted" in llm.calls[2][-1]


def test_agent_raises_if_no_final_report(sample_repo):
    llm = FakeLLM([{"tool_calls": [{"tool": "git_log", "args": {}}]}, "garbage"])
    with pytest.raises(AgentError):
        Agent(llm, RepoTools(sample_repo), max_steps=1).run("https://github.com/x/y")


def test_hallucinated_file_is_dropped(sample_repo):
    llm = FakeLLM([{"finish": True, "violations": [
        {"category": "security", "severity": "high", "file": "secrets/prod.env", "line": 1, "description": "x"}]}])
    assert Agent(llm, RepoTools(sample_repo), max_steps=3).run("u") == []


def test_parse_reply_handles_fences_and_extra_text():
    assert parse_reply('```json\n{"finish": true}\n```') == {"finish": True}
    assert parse_reply('sure: {"a": 1} thanks') == {"a": 1}
    assert parse_reply('{"a": 1}\n{"b": 2}') == {"a": 1}

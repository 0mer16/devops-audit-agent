import pytest

import agent


def test_invalid_repo_url_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit) as exc:
        agent.main(["--repo", "not-a-url", "--output", str(tmp_path / "r.json")])
    assert exc.value.code == 2


def test_missing_api_key_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(agent, "load_env", lambda: None)
    with pytest.raises(SystemExit) as exc:
        agent.main(["--repo", "https://github.com/a/b", "--output", str(tmp_path / "r.json")])
    assert exc.value.code == 2


def test_url_pattern():
    assert agent.REPO_URL_RE.match("https://github.com/owner/repo")
    assert agent.REPO_URL_RE.match("https://github.com/owner/repo.git")
    assert not agent.REPO_URL_RE.match("https://gitlab.com/owner/repo")
    assert not agent.REPO_URL_RE.match("https://github.com/owner")

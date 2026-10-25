import subprocess

import pytest

from tools import RepoTools, ToolError, dispatch


def test_list_files_only_tracked(sample_repo):
    out = RepoTools(sample_repo).list_files()
    assert "app.py" in out
    assert ".github/workflows/ci.yml" in out
    assert "ignored.log" not in out


def test_list_files_subdirectory(sample_repo):
    out = RepoTools(sample_repo).list_files(".github")
    assert "ci.yml" in out and "app.py" not in out


def test_read_file_has_line_numbers_and_redacts(sample_repo):
    out = RepoTools(sample_repo).read_file("app.py")
    assert "2: API_KEY" in out
    assert "abcd1234efgh5678ijkl" not in out
    assert "redacted" in out


def test_read_file_missing(sample_repo):
    assert dispatch(RepoTools(sample_repo), "read_file", {"path": "nope.py"}).startswith("ERROR")


def test_path_traversal_blocked(sample_repo):
    with pytest.raises(ToolError):
        RepoTools(sample_repo).read_file("../../etc/passwd")


def test_search_code_finds_and_masks(sample_repo):
    out = RepoTools(sample_repo).search_code("api_key")
    assert "app.py:2:" in out
    assert "abcd1234efgh5678ijkl" not in out


def test_search_code_with_glob(sample_repo):
    out = RepoTools(sample_repo).search_code("pytest", file_glob="*.yml")
    assert "ci.yml" in out


def test_search_invalid_regex(sample_repo):
    assert dispatch(RepoTools(sample_repo), "search_code", {"pattern": "("}).startswith("ERROR: invalid regex")


def test_git_log(sample_repo):
    out = RepoTools(sample_repo).git_log()
    assert "first commit" in out and "app.py" in out


def test_inspect_workflows(sample_repo):
    out = RepoTools(sample_repo).inspect_workflows()
    assert "write-all" in out
    assert "pytest || true" in out
    assert "continue-on-error=True" in out


def test_run_ruff_does_not_crash(sample_repo):
    out = RepoTools(sample_repo).run_ruff()
    assert isinstance(out, str) and out


def test_dispatch_unknown_tool_and_bad_args(sample_repo):
    tools = RepoTools(sample_repo)
    assert "unknown tool" in dispatch(tools, "rm_rf", {})
    assert "unexpected args" in dispatch(tools, "git_log", {"foo": 1})


def test_not_a_repo(tmp_path):
    with pytest.raises(ToolError):
        RepoTools(tmp_path)


def test_tools_do_not_modify_repo(sample_repo):
    tools = RepoTools(sample_repo)
    tools.list_files()
    tools.read_file("app.py")
    tools.search_code("x")
    tools.git_log()
    tools.inspect_workflows()
    tools.run_ruff()
    status = subprocess.run(["git", "-C", str(sample_repo), "status", "--porcelain"],
                            capture_output=True, text=True, check=True).stdout
    assert status.strip() == "?? ignored.log"

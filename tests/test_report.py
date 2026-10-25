from report import normalize_violations
from tools import RepoTools

FIELDS = {"rule_id", "category", "severity", "file", "line", "description", "evidence", "recommendation"}


def test_fills_and_fixes_fields(sample_repo):
    raw = [{"category": "Security", "severity": "CRITICAL", "file": "./app.py", "line": "2",
            "description": "Hardcoded key", "evidence": 'API_KEY = "abcd1234efgh5678ijkl"'}]
    out, _ = normalize_violations(raw, RepoTools(sample_repo))
    v = out[0]
    assert v["category"] == "security" and v["severity"] == "critical"
    assert v["file"] == "app.py" and v["line"] == 2
    assert v["rule_id"].startswith("SEC-")
    assert "abcd1234efgh5678ijkl" not in v["evidence"]
    assert set(v) == FIELDS


def test_drops_nonexistent_files_and_duplicates(sample_repo):
    wf = ".github/workflows/ci.yml"
    raw = [
        {"category": "ci", "severity": "high", "file": "missing.yml", "description": "x"},
        {"category": "ci", "severity": "high", "file": wf, "line": 10, "description": "Tests never fail"},
        {"category": "ci", "severity": "high", "file": wf, "line": 10, "description": "Tests never fail"},
    ]
    out, notes = normalize_violations(raw, RepoTools(sample_repo))
    assert len(out) == 1 and out[0]["file"] == wf
    assert len(notes) == 2


def test_dotfiles_kept(sample_repo):
    (sample_repo / ".gitignore").write_text("x\n")
    out, _ = normalize_violations([{"category": "repository_hygiene", "file": ".gitignore",
                                    "description": "weak gitignore"}], RepoTools(sample_repo))
    assert out[0]["file"] == ".gitignore"


def test_null_file_and_bad_severity(sample_repo):
    out, _ = normalize_violations([{"category": "testing", "severity": "weird", "file": None,
                                    "line": 999, "description": "No tests"}], RepoTools(sample_repo))
    assert out[0]["file"] is None and out[0]["severity"] == "medium"


def test_line_beyond_file_end_cleared(sample_repo):
    out, _ = normalize_violations([{"category": "security", "file": "app.py", "line": 500,
                                    "description": "x"}], RepoTools(sample_repo))
    assert out[0]["line"] is None


def test_not_a_list():
    out, notes = normalize_violations({"a": 1})
    assert out == [] and notes

import subprocess

import pytest


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def sample_repo(tmp_path):
    """A tiny git repo with a few planted problems."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "tester")
    (repo / "README.md").write_text("# demo\n")
    (repo / "app.py").write_text('import os\nAPI_KEY = "abcd1234efgh5678ijkl"\nDB = os.getenv("DB_URL")\n')
    (repo / "requirements.txt").write_text("flask\n")
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        "name: CI\non: [push]\npermissions: write-all\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/checkout@v4\n      - name: Tests\n        run: pytest || true\n"
        "        continue-on-error: true\n"
    )
    (repo / "ignored.log").write_text("not tracked\n")
    _git(repo, "add", "README.md", "app.py", "requirements.txt", ".github")
    _git(repo, "commit", "-q", "-m", "first commit")
    return repo

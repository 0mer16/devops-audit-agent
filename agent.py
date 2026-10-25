"""CLI entry point.

    python agent.py --repo https://github.com/owner/name --output report.json
"""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+?(\.git)?/?$")
CLONE_TIMEOUT = 300


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def fail(msg, code):
    log(f"error: {msg}")
    sys.exit(code)


def load_env():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env")


def clone_repo(url, dest):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    cmd = ["git", "clone", "--quiet", "--depth", "200", "--no-tags", url, dest]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=CLONE_TIMEOUT, env=env)
    except FileNotFoundError:
        raise RuntimeError("git is not installed")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"git clone timed out after {CLONE_TIMEOUT}s")
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr.strip()[:300]}")


def _remove_readonly(func, path, _exc):
    # git marks pack files read-only, which breaks rmtree on Windows
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="LLM agent that audits a GitHub repository for DevOps issues")
    parser.add_argument("--repo", required=True, help="public GitHub repository URL")
    parser.add_argument("--output", required=True, help="where to write the JSON report")
    parser.add_argument("--max-steps", type=int, default=25, help="max agent turns (default 25)")
    parser.add_argument("--model", default=None, help="Gemini model (default: GEMINI_MODEL or gemini-flash-latest)")
    parser.add_argument("--trace", default=None, help="optional path to write the tool-call trace as JSON")
    args = parser.parse_args(argv)

    repo_url = args.repo.strip()
    if not REPO_URL_RE.match(repo_url):
        fail("--repo must look like https://github.com/<owner>/<repo>", 2)
    if args.max_steps < 1:
        fail("--max-steps must be at least 1", 2)

    load_env()
    from llm import GeminiLLM, LLMError
    from loop import Agent, AgentError
    from report import build_report
    from tools import RepoTools, ToolError

    try:
        llm = GeminiLLM(os.environ.get("GEMINI_API_KEY"), args.model or os.environ.get("GEMINI_MODEL"))
    except LLMError as exc:
        fail(f"{exc} (copy .env.example to .env and add your key)", 2)

    workdir = tempfile.mkdtemp(prefix="audit_")
    clone_dir = os.path.join(workdir, "repo")
    agent = None
    try:
        log(f"cloning {repo_url} ...")
        try:
            clone_repo(repo_url, clone_dir)
            tools = RepoTools(clone_dir)
        except (RuntimeError, ToolError) as exc:
            fail(str(exc), 3)

        agent = Agent(llm, tools, max_steps=args.max_steps, log=log)
        try:
            violations = agent.run(repo_url)
        except (LLMError, AgentError) as exc:
            fail(str(exc), 4)

        report = build_report(repo_url.rstrip("/"), violations)
        out_path = Path(args.output)
        if out_path.parent and not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        log(f"wrote {len(violations)} violations to {out_path}")
    except OSError as exc:
        fail(f"could not write report: {exc}", 5)
    except KeyboardInterrupt:
        fail("interrupted", 130)
    finally:
        if args.trace and agent is not None:
            try:
                Path(args.trace).write_text(json.dumps(agent.trace, indent=2), encoding="utf-8")
            except OSError:
                log("warning: could not write trace file")
        if sys.version_info >= (3, 12):
            shutil.rmtree(workdir, onexc=_remove_readonly)
        else:
            shutil.rmtree(workdir, onerror=_remove_readonly)
    return 0


if __name__ == "__main__":
    sys.exit(main())

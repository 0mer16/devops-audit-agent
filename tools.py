"""Inspection tools the agent can call.

All tools are read-only. They never run code from the inspected repository
(ruff only parses the files, it does not import or execute them).
"""

import fnmatch
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from redact import redact

MAX_OUTPUT_CHARS = 12000
MAX_FILE_LINES = 400
MAX_FILE_BYTES = 1_000_000
CMD_TIMEOUT = 60


class ToolError(Exception):
    pass


def _truncate(text, limit=MAX_OUTPUT_CHARS):
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [output truncated, {len(text) - limit} more characters]"


class RepoTools:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not (self.root / ".git").exists():
            raise ToolError(f"{self.root} is not a git repository")
        self._files = None

    # ---------- helpers ----------

    def _git(self, *args):
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=CMD_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"git {' '.join(args)} timed out")
        if result.returncode != 0:
            raise ToolError(result.stderr.strip() or f"git {args[0]} failed")
        return result.stdout

    def _safe_path(self, path):
        if not isinstance(path, str) or not path.strip():
            raise ToolError("path must be a non-empty string")
        full = (self.root / path.strip().lstrip("/\\")).resolve()
        if full != self.root and self.root not in full.parents:
            raise ToolError("path is outside the repository")
        return full

    def tracked_files(self):
        """Files tracked by git (so committed junk shows up, ignored files don't)."""
        if self._files is None:
            out = self._git("ls-files", "-z")
            self._files = sorted(f for f in out.split("\0") if f)
        return self._files

    def file_exists(self, path):
        try:
            return self._safe_path(path).is_file()
        except ToolError:
            return False

    def line_count(self, path):
        try:
            with open(self._safe_path(path), "rb") as fh:
                return sum(1 for _ in fh)
        except (OSError, ToolError):
            return None

    @staticmethod
    def _is_binary(data):
        return b"\0" in data[:4096]

    # ---------- tools ----------

    def list_files(self, directory=""):
        files = self.tracked_files()
        if directory:
            prefix = directory.strip("/\\").replace("\\", "/") + "/"
            files = [f for f in files if f.startswith(prefix)]
        if not files:
            return "No tracked files found" + (f" under '{directory}'" if directory else "")
        lines = []
        for f in files[:600]:
            try:
                size = (self.root / f).stat().st_size
            except OSError:
                size = -1
            lines.append(f"{f} ({size} bytes)")
        header = f"{len(files)} tracked files"
        if len(files) > 600:
            header += " (showing first 600)"
        return header + ":\n" + "\n".join(lines)

    def read_file(self, path, start_line=1, end_line=None):
        full = self._safe_path(path)
        if not full.is_file():
            raise ToolError(f"file not found: {path}")
        if full.stat().st_size > MAX_FILE_BYTES:
            raise ToolError(f"file too large to read ({full.stat().st_size} bytes)")
        data = full.read_bytes()
        if self._is_binary(data):
            return f"{path} is a binary file ({len(data)} bytes)"
        lines = data.decode("utf-8", errors="replace").splitlines()
        start = max(1, int(start_line or 1))
        end = int(end_line) if end_line else start + MAX_FILE_LINES - 1
        end = min(end, len(lines), start + MAX_FILE_LINES - 1)
        body = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
        footer = ""
        if end < len(lines):
            footer = f"\n... [{len(lines) - end} more lines, use start_line={end + 1}]"
        return _truncate(redact(f"{path} ({len(lines)} lines)\n{body}{footer}"))

    def search_code(self, pattern, file_glob=None, max_results=60):
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except (re.error, TypeError) as exc:
            raise ToolError(f"invalid regex: {exc}")
        max_results = max(1, min(int(max_results or 60), 200))
        hits = []
        for f in self.tracked_files():
            if file_glob and not (fnmatch.fnmatch(f, file_glob) or fnmatch.fnmatch(Path(f).name, file_glob)):
                continue
            full = self.root / f
            try:
                if full.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = full.read_bytes()
            except OSError:
                continue
            if self._is_binary(data):
                continue
            for no, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{f}:{no}: {line.strip()[:200]}")
                    if len(hits) >= max_results:
                        break
            if len(hits) >= max_results:
                break
        if not hits:
            return f"No matches for /{pattern}/"
        suffix = f"\n[stopped at {max_results} matches]" if len(hits) >= max_results else ""
        return _truncate(redact("\n".join(hits) + suffix))

    def git_log(self, max_count=30):
        max_count = max(1, min(int(max_count or 30), 100))
        out = self._git("log", f"-n{max_count}", "--date=short",
                        "--pretty=format:--- %h %ad %an: %s", "--name-status")
        return _truncate(redact(out.strip() or "No commits"))

    def inspect_workflows(self):
        """Summarise every GitHub Actions workflow: triggers, permissions, jobs, steps."""
        wf_files = [f for f in self.tracked_files()
                    if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))]
        if not wf_files:
            return "No GitHub Actions workflows in .github/workflows/"
        parts = []
        for f in wf_files:
            try:
                doc = yaml.safe_load((self.root / f).read_text(encoding="utf-8", errors="replace"))
            except yaml.YAMLError as exc:
                parts.append(f"## {f}\nYAML PARSE ERROR: {exc}")
                continue
            if not isinstance(doc, dict):
                parts.append(f"## {f}\nnot a mapping (invalid workflow)")
                continue
            # PyYAML turns the bare key `on` into True
            triggers = doc.get("on", doc.get(True))
            lines = [f"## {f}", f"name: {doc.get('name')}", f"triggers: {triggers}",
                     f"top-level permissions: {doc.get('permissions', 'NOT SET (repo default)')}"]
            for job_id, job in (doc.get("jobs") or {}).items():
                if not isinstance(job, dict):
                    continue
                lines.append(f"job '{job_id}': runs-on={job.get('runs-on')} needs={job.get('needs')} "
                             f"if={job.get('if')} environment={job.get('environment')} "
                             f"permissions={job.get('permissions')} continue-on-error={job.get('continue-on-error')}")
                for step in job.get("steps") or []:
                    if not isinstance(step, dict):
                        continue
                    desc = step.get("uses") or (str(step.get("run", "")).strip().replace("\n", " ; ")[:160])
                    extra = []
                    for key in ("if", "continue-on-error"):
                        if key in step:
                            extra.append(f"{key}={step[key]}")
                    lines.append(f"  - {step.get('name', '(unnamed)')}: {desc} {' '.join(extra)}".rstrip())
            parts.append("\n".join(lines))
        return _truncate(redact("\n\n".join(parts)))

    def run_ruff(self):
        """Static lint with ruff. Parses files only, nothing from the repo is executed."""
        exe = shutil.which("ruff")
        if not exe:
            return "CHECK UNAVAILABLE: ruff is not installed, do not draw conclusions from this"
        if not any(f.endswith(".py") for f in self.tracked_files()):
            return "No Python files to lint"
        try:
            result = subprocess.run(
                [exe, "check", "--no-cache", "--exit-zero", "--output-format", "concise",
                 "--select", "E9,F", "."],
                cwd=self.root, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=CMD_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return "CHECK UNAVAILABLE: ruff timed out"
        out = (result.stdout + result.stderr).strip()
        return _truncate(redact(out or "ruff: no issues found (rules E9,F)"))


# Tool descriptions shown to the LLM. args: name -> description
TOOL_SPECS = {
    "list_files": {
        "description": "List files tracked by git (with sizes). Optional 'directory' to list only a subfolder.",
        "args": {"directory": "optional subfolder, e.g. 'src'"},
    },
    "read_file": {
        "description": "Read a file with line numbers (max 400 lines per call). Secrets are masked.",
        "args": {"path": "file path relative to repo root", "start_line": "optional int",
                 "end_line": "optional int"},
    },
    "search_code": {
        "description": "Case-insensitive regex search over all tracked text files. Returns file:line: text.",
        "args": {"pattern": "python regex", "file_glob": "optional glob e.g. '*.py' or '.github/*'",
                 "max_results": "optional int (default 60)"},
    },
    "git_log": {
        "description": "Recent commit history with changed files (A/M/D) per commit.",
        "args": {"max_count": "optional int (default 30)"},
    },
    "inspect_workflows": {
        "description": "Parsed summary of all GitHub Actions workflows: triggers, permissions, jobs, steps, if-conditions, continue-on-error.",
        "args": {},
    },
    "run_ruff": {
        "description": "Run ruff static analysis (syntax errors + pyflakes rules) on the Python code. Does not execute repo code.",
        "args": {},
    },
}


def dispatch(tools, name, args):
    """Run a tool by name. Errors are returned as text so the agent can react to them."""
    if name not in TOOL_SPECS:
        return f"ERROR: unknown tool '{name}'. Available: {', '.join(TOOL_SPECS)}"
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return "ERROR: args must be a JSON object"
    allowed = set(TOOL_SPECS[name]["args"])
    unknown = set(args) - allowed
    if unknown:
        return f"ERROR: unexpected args {sorted(unknown)} for {name}. Allowed: {sorted(allowed)}"
    try:
        return getattr(tools, name)(**args)
    except ToolError as exc:
        return f"ERROR: {exc}"
    except (TypeError, ValueError) as exc:
        return f"ERROR: bad arguments for {name}: {exc}"
    except Exception as exc:  # a broken tool must not kill the whole audit
        return f"ERROR: {name} failed: {type(exc).__name__}: {exc}"

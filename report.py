"""Cleans up the violations returned by the model before they are written out."""

from redact import redact

SEVERITIES = ("critical", "high", "medium", "low")
CATEGORIES = ("repository_hygiene", "dependency_management", "code_quality", "testing", "ci",
              "security", "configuration", "collaboration", "build_release")
CATEGORY_ALIASES = {
    "hygiene": "repository_hygiene", "repository hygiene": "repository_hygiene",
    "dependencies": "dependency_management", "dependency management": "dependency_management",
    "code quality": "code_quality", "tests": "testing", "github actions": "ci",
    "github_actions": "ci", "ci/cd": "ci", "build": "build_release", "release": "build_release",
    "build and release": "build_release", "config": "configuration",
}
PREFIXES = {"repository_hygiene": "HYG", "dependency_management": "DEP", "code_quality": "CQ",
            "testing": "TEST", "ci": "CI", "security": "SEC", "configuration": "CFG",
            "collaboration": "COL", "build_release": "BLD"}
FIELDS = ("rule_id", "category", "severity", "file", "line", "description", "evidence", "recommendation")


def _text(value):
    return redact(str(value).strip()) if value is not None else ""


def normalize_violations(raw, tools=None):
    """Validate, fix up and de-duplicate violations.

    tools: RepoTools used to check that a referenced file really exists, so
    findings about files the model never saw (hallucinations) are dropped.
    Returns (violations, notes) where notes explain anything that was dropped.
    """
    notes = []
    if not isinstance(raw, list):
        return [], ["violations was not a list"]
    out, seen = [], set()
    counters = {}
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            notes.append(f"item {i} dropped: not an object")
            continue
        description = _text(item.get("description"))
        if not description:
            notes.append(f"item {i} dropped: no description")
            continue

        category = str(item.get("category") or "").strip().lower()
        category = CATEGORY_ALIASES.get(category, category.replace(" ", "_"))
        if category not in CATEGORIES:
            category = "code_quality"

        severity = str(item.get("severity") or "").strip().lower()
        if severity not in SEVERITIES:
            severity = "medium"

        file = item.get("file")
        if file in (None, "", "null"):
            file = None
        else:
            file = str(file).strip().replace("\\", "/")
            while file.startswith("./"):
                file = file[2:]
            file = file.lstrip("/") or None
        line = item.get("line")
        try:
            line = int(line) if line not in (None, "", "null") else None
        except (TypeError, ValueError):
            line = None
        if line is not None and line < 1:
            line = None

        if tools is not None and file is not None:
            if not tools.file_exists(file):
                notes.append(f"item {i} dropped: file '{file}' does not exist in the repository")
                continue
            total = tools.line_count(file)
            if line is not None and total is not None and line > total:
                line = None

        key = (category, file, line, description.lower()[:60])
        if key in seen:
            notes.append(f"item {i} dropped: duplicate")
            continue
        seen.add(key)

        rule_id = str(item.get("rule_id") or "").strip().upper()
        if not rule_id:
            counters[category] = counters.get(category, 0) + 1
            rule_id = f"{PREFIXES[category]}-{counters[category]:03d}"

        out.append({
            "rule_id": rule_id,
            "category": category,
            "severity": severity,
            "file": file,
            "line": line,
            "description": description,
            "evidence": _text(item.get("evidence")) or "See referenced file",
            "recommendation": _text(item.get("recommendation")) or "Review and fix this issue",
        })
    order = {s: n for n, s in enumerate(SEVERITIES)}
    out.sort(key=lambda v: (order[v["severity"]], v["category"], v["file"] or ""))
    return out, notes


def build_report(repo_url, violations):
    return {"repository": repo_url, "violations": violations}

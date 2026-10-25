"""Masks secret values so they never end up in logs, prompts or the report."""

import re

# well known token formats
TOKEN_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),                       # AWS access key id
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),              # GitHub tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                  # OpenAI style keys
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),                  # Google API keys
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),           # Slack tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)"),
]

SECRET_NAME = r"[\w.\-]*(?:key|secret|token|passw(?:or)?d|pwd|credential)[\w.\-]*"

# NAME = "value"  /  NAME: 'value'
QUOTED_ASSIGN = re.compile(
    r"(?i)(" + SECRET_NAME + r"[\"']?\s*[:=]\s*)([\"'])([^\"'\n]{8,})\2"
)
# NAME=value / NAME: value (env files, yaml) - skip ${{ }}, $VAR and function calls
UNQUOTED_ASSIGN = re.compile(
    r"(?im)^(\s*(?:export\s+)?" + SECRET_NAME + r"\s*[:=]\s*)([^\s\"'#$(][^\s#]{7,})\s*$"
)

PLACEHOLDER_HINTS = ("your", "example", "changeme", "change_me", "xxx", "placeholder",
                     "dummy", "<", "replace", "todo", "secrets.", "os.environ", "getenv")


def _looks_like_placeholder(value):
    v = value.lower()
    return any(h in v for h in PLACEHOLDER_HINTS)


def redact(text):
    """Return text with secret-looking values replaced by a marker.

    The variable name is kept so the agent can still see that a literal
    value was assigned, but the value itself is never shown.
    """
    if not text:
        return text
    for pat in TOKEN_PATTERNS:
        text = pat.sub("<redacted-token>", text)

    def _quoted(m):
        if _looks_like_placeholder(m.group(3)):
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}<redacted-literal len={len(m.group(3))}>{m.group(2)}"

    def _unquoted(m):
        if _looks_like_placeholder(m.group(2)):
            return m.group(0)
        return f"{m.group(1)}<redacted-literal len={len(m.group(2))}>"

    text = QUOTED_ASSIGN.sub(_quoted, text)
    text = UNQUOTED_ASSIGN.sub(_unquoted, text)
    return text

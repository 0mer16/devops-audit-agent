# devops-audit-agent

This is my Assignment 2 for MLOps. It's an agent that takes a public GitHub repo, looks
through it with a set of tools, and writes a JSON report of DevOps problems it found
(CI issues, leaked secrets, missing tests, bad gitignore, etc).

The LLM (Gemini) decides which tool to call next based on what it has seen so far. I
wrote the loop myself in plain Python, no LangChain / LangGraph or any agent framework,
just the `google-genai` SDK.

## Setup

Needs Python 3.10+ and git.

```
git clone https://github.com/0mer16/devops-audit-agent.git
cd devops-audit-agent
python -m venv .venv
.venv\Scripts\activate        # on linux/mac: source .venv/bin/activate
pip install -r requirements.txt
```

Then copy `.env.example` to `.env` and put your Gemini API key in it:

```
GEMINI_API_KEY=your key here
GEMINI_MODEL=gemini-flash-latest
```

You can get a free key from https://aistudio.google.com/apikey. If one model is busy
(503) you can switch models with `GEMINI_MODEL` or `--model`.

## Running it

```
python agent.py --repo https://github.com/owner/repo --output report.json
```

Optional flags:
- `--max-steps 25` how many turns the agent gets (default 25)
- `--model <name>` override the Gemini model
- `--trace trace.json` save every tool call the agent made

Progress (each tool call) is printed to stderr. Exit codes: 0 ok, 2 bad input / missing
key, 3 clone failed, 4 LLM or agent failure, 5 couldn't write the report.

## How it works

```
agent.py   -> checks args, clones the repo into a temp folder, runs the agent, writes JSON, deletes the clone
loop.py    -> the agent loop
llm.py     -> small Gemini wrapper (retries on 429/503)
prompts.py -> system prompt (inspection areas, evidence rules, severity guide)
tools.py   -> the inspection tools
report.py  -> cleans up the model's findings before writing them
redact.py  -> masks secrets so they never get printed or sent anywhere
```

The loop goes like this:
1. The model gets the repo URL and the list of tools.
2. Each turn it replies with JSON: its reasoning plus 1-5 tool calls it wants to run.
3. I run those tools and send the outputs back.
4. It repeats until the model replies with `"finish": true` and its list of violations,
   or until it runs out of steps (then it's asked for a final answer).

Bad JSON or unknown tools don't crash it, the error gets sent back to the model so it can
fix it.

### Tools

| Tool | What it does |
|---|---|
| `list_files(directory)` | files tracked by git (so committed junk shows up) |
| `read_file(path, start_line, end_line)` | reads a file with line numbers |
| `search_code(pattern, file_glob)` | regex search across the repo |
| `git_log(max_count)` | recent commits and which files changed |
| `inspect_workflows()` | parsed GitHub Actions workflows: triggers, permissions, steps, `continue-on-error` |
| `run_ruff()` | static lint with ruff (only parses files, doesn't run them) |

### Trying to avoid false positives

- The prompt tells the model to only report things it actually saw in tool output, and
  not to count missing optional files when an alternative exists (e.g. pyproject.toml
  instead of requirements.txt). It also can't see branch protection, so it's told not
  to guess about it.
- `report.py` drops findings that point at files that don't exist in the repo,
  removes duplicates, fixes severity/category values and clears line numbers past the
  end of the file.

### Safety

- The target repo is only read. It's cloned into a temp folder that gets deleted at the end.
- Nothing from the repo is executed. I left out running the repo's tests on purpose,
  because that would mean running untrusted code without a sandbox.
- Secret values are masked (`<redacted-literal len=N>`) in tool output before the model
  sees them, and again in the report.
- Paths are checked so tools can't read outside the cloned repo.

## Tests

```
pytest
```

The tests build a small git repo with some planted problems and test the tools on it.
The agent loop is tested with a fake LLM that returns scripted replies, so the tests
don't need an API key.

## Sample output

`sample_report.json` is a real report from running the agent on my CD activity repo
(https://github.com/0mer16/mlops_activity).

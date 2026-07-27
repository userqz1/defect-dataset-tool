---
name: run
description: Launches the desktop app in the background using the project's conda env python. Use whenever the user says "运行" / "run" / "试一下".
---

Start the app and return immediately. Do not block the conversation waiting for the GUI to close.

Steps:

1. Use the shell tool with `run_in_background: true`.
2. Command: `conda run --no-capture-output -n defect-tool python main.py` — run it from the project root (the tool's working directory already is the project root; do not `cd` to an absolute path).
3. Description: `run app`.
4. After the tool call returns, write one short sentence telling the user the app started, and ask them to report what they see. Do not poll the background task.

When the task notification arrives later:

- Read the output file with Bash `tail` only if the exit code is non-zero, or if the user reports a problem.
- If the exit code is 0 and the user has not reported an issue, do not pull logs preemptively — exit code 0 from a GUI app means the user closed the window normally.
- If the exit code is non-zero, fetch the last ~30 lines of the output file, identify the traceback's root cause, propose a fix, and wait for confirmation before editing.

Notes:
- Env is `defect-tool` (Python 3.11) with conda on PATH (`condabin`). Always go through `conda run -n defect-tool` — a bare `python` on PATH resolves to the wrong interpreter (Python312 / WindowsApps) and fails with import errors. Never hardcode an absolute interpreter path; `conda run` resolves the env wherever it is installed.
- If a long-lived agent shell doesn't resolve `conda` (stale PATH snapshot), reload PATH from the registry first — portable, no hardcoded paths:
  `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`

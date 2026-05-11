---
name: run
description: Launches the desktop app in the background using the project's conda env python. Use whenever the user says "运行" / "run" / "试一下".
---

Start the app and return immediately. Do not block the conversation waiting for the GUI to close.

Steps:

1. Use the Bash tool with `run_in_background: true`.
2. Command: `cd "C:/Users/zq/Desktop/defect_dataset_tool" && "C:/ProgramData/miniconda3/envs/defect-tool/python.exe" main.py`
3. Description: `run app`.
4. After the tool call returns, write one short sentence telling the user the app started, and ask them to report what they see. Do not poll the background task.

When the task notification arrives later:

- Read the output file with Bash `tail` only if the exit code is non-zero, or if the user reports a problem.
- If the exit code is 0 and the user has not reported an issue, do not pull logs preemptively — exit code 0 from a GUI app means the user closed the window normally.
- If the exit code is non-zero, fetch the last ~30 lines of the output file, identify the traceback's root cause, propose a fix, and wait for confirmation before editing.

Never use `python main.py` without the full env path — `python` on PATH is the wrong interpreter on this machine and will fail with import errors.

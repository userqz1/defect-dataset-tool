---
name: check
description: Runs project health checks — core purity, GUI styling rules, and Python compile — and reports a single combined summary. Use before commits or when the user asks "检查一下" / "有没有问题".
---

Run all health checks in parallel and combine the results into one report.

Steps:

1. In a single message, launch three things in parallel:
   - Agent `core-guardian` with prompt: "Audit core/ for purity violations. Report only violations and warnings, no clean-file enumeration."
   - Agent `style-cop` with prompt: "Audit gui/views and gui/widgets against the three-layer styling rules. Report violations, borderline cases, and stats."
   - Bash command (foreground, fast): `"C:/ProgramData/miniconda3/envs/defect-tool/python.exe" -m compileall -q core gui main.py` with description `compile check`. Capture the exit code.

2. While agents are running, do nothing else — wait for all three to return.

3. Combine into a single report with three sections:
   - **Compile** — pass/fail and any error output.
   - **Core purity** — agent's violations + warnings, verbatim.
   - **GUI styling** — agent's violations + borderline + stats, verbatim.

4. End with a single-line verdict: `✅ All clean` or `⚠ N issues to review` (where N is total violations across both agents).

Do not propose fixes unless the user asks. The skill is read-only.

---
name: profile-scan
description: Profiles core.dataset.scan_dataset + count_annotations against a dataset path to find performance hotspots. Use when the user says "扫描慢" or wants to validate a scan-speed change.
---

Take one argument: the dataset root path. If missing, ask the user to provide it.

Steps:

1. Write a small profiling driver to a temp file (not inside the project tree) that:
   - Imports `core.dataset.scan_dataset` and `core.dataset.count_annotations`.
   - Runs both phases under `cProfile`.
   - Prints the top 25 cumulative-time functions, filtered to rows whose filename contains `core/` or `site-packages` hotspots.
   - Also prints: total images scanned, total annotations counted, Phase 1 wall time, Phase 2 wall time.

2. Run the driver with the project's python: `"C:/ProgramData/miniconda3/envs/defect-tool/python.exe" <temp_file> <dataset_path>`. Use a generous timeout (up to 10 minutes) since large datasets take a while.

3. Report:
   - Phase 1 and Phase 2 wall clock times.
   - Top 10 hotspots with cumulative time and call count.
   - One paragraph identifying the likely bottleneck (I/O bound, JSON parsing, hashing, etc.).
   - Two or three concrete optimization suggestions, ordered by expected impact.

4. Delete the temp file.

Rules:

- Do not modify `core/` as part of this skill. This is a read-only diagnostic.
- Do not write the profiling driver into the project tree; it is throwaway.
- If the dataset path is invalid or not a directory, stop immediately with a clear error.

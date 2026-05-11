---
name: tokens
description: Prints the current Tokens dataclass fields and the LIGHT/DARK values side by side. Use when picking colors/spacing for a new widget or reviewing the design system.
---

Read `gui/theme.py` and print a compact reference of the design tokens.

Steps:

1. Read `gui/theme.py`.
2. Identify the `Tokens` dataclass fields (colors first, then geometry/spacing, then sizing).
3. Identify the `LIGHT` and `DARK` instances.
4. Output a Markdown table: `Token | LIGHT | DARK | Category`.
5. After the table, list any constants that exist in `LIGHT`/`DARK` but are not declared as fields on `Tokens` (these are bugs — flag them).
6. One-line summary at the end: total token count, and which file to edit to add a new one.

Read only. Do not edit.

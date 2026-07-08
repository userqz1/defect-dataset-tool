"""Label normalization helpers shared by import, edit, and export paths."""
from __future__ import annotations


def normalize_label(value: object) -> str:
    """Return a stable class/region label for model and export use.

    Annotation tools occasionally leave BOMs or trailing newlines in class
    names.  Treat all whitespace runs as a single space so labels such as
    ``"fastener_core\n"`` match the project class ``"fastener_core"``.
    """
    if value is None:
        return ""
    text = str(value).replace("\ufeff", "")
    return " ".join(text.split())

"""PairedFolder schema for image-pair learning tasks."""
from __future__ import annotations

from ..exporter.pairedfolder import (
    PairedFolderExportOptions,
    export_pairedfolder,
)
from ..models import Dataset
from ..task_types import TaskType
from .base import Schema, Slot, SlotStatus
from .common_validators import images_slot, split_pending_slot


def _validate_pair_rule(dataset: Dataset) -> SlotStatus:
    n_img = sum(c.image_count for c in dataset.categories)
    ok = n_img >= 2
    return SlotStatus(
        ok=ok,
        current_text=(
            "pairs.csv or same-stem A/B inference"
            if ok else "not enough images"
        ),
        required_text="paired images",
        action_text="" if ok else "import at least one image pair",
        fix_command="" if ok else "ingest",
        count=n_img,
        target=2,
    )


PAIREDFOLDER_SCHEMA = Schema(
    key="PairedFolder",
    display_name="PairedFolder",
    description="Image-pair split folders with a pairs.csv manifest",
    task_types=(TaskType.IMAGE_PAIR,),
    slots=(
        images_slot(2),
        Slot("pairs", "pairing rule", "meta", required=True,
             validator=_validate_pair_rule),
        split_pending_slot(),
    ),
    options_class=PairedFolderExportOptions,
    writer=export_pairedfolder,
    directory_preview="pairs.csv + images/{split}/a/ + images/{split}/b/",
)

"""Tests for VLM conversation round-trip: write → read → Sample → export.

Covers: sidecar .conversations.json persistence, Sample.conversations
field, DetailView-level save flow (signal emission), and export through
LLaVA / ShareGPT / Swift formats consuming conversation data.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from core.annotation_writer import (
    conversation_sidecar_path,
    read_conversations,
    write_conversations,
)
from core.format_out import ExportOptions, export_samples
from core.unified import Region, Sample, SampleSet


# ── Helpers ────────────────────────────────────────────────────────────

def _make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (100, 150, 200)).save(path)


_SIMPLE_CONVOS = [
    {"from": "human", "value": "<image>\nDescribe this image."},
    {"from": "gpt", "value": "A surface with a crack defect."},
]

_MULTI_TURN = [
    {"from": "human", "value": "<image>\nWhat do you see?"},
    {"from": "gpt", "value": "A metal surface with a scratch."},
    {"from": "human", "value": "How severe is it?"},
    {"from": "gpt", "value": "It appears to be a minor surface scratch."},
]


def _conv_sample_set(
    tmp_path: Path,
    conversations_list: list[list[dict[str, str]]],
    split: str = "train",
) -> SampleSet:
    """Build SampleSet with images on disk and conversations fields set."""
    samples = []
    for i, convos in enumerate(conversations_list):
        ip = tmp_path / "images" / f"img_{i:03d}.png"
        _make_image(ip)
        s = Sample(
            image_path=ip,
            image_width=64, image_height=64,
            category="test",
            conversations=convos,
            split=split,
        )
        samples.append(s)
    return SampleSet(samples=samples)


# ── Sidecar write / read ─────────────────────────────────────────────

class TestConversationSidecar:
    def test_sidecar_path(self, tmp_path):
        img = tmp_path / "photo.jpg"
        p = conversation_sidecar_path(img)
        assert p.name == "photo.conversations.json"
        assert p.parent == tmp_path

    def test_write_creates_json(self, tmp_path):
        img = tmp_path / "photo.jpg"
        _make_image(img)
        p = write_conversations(img, _SIMPLE_CONVOS)
        assert p.exists()
        assert p.suffix == ".json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["from"] == "human"
        assert data[1]["from"] == "gpt"

    def test_read_roundtrip(self, tmp_path):
        img = tmp_path / "photo.jpg"
        _make_image(img)
        write_conversations(img, _MULTI_TURN)
        result = read_conversations(img)
        assert len(result) == 4
        assert result[0]["from"] == "human"
        assert result[1]["value"] == "A metal surface with a scratch."
        assert result[2]["from"] == "human"
        assert result[3]["from"] == "gpt"

    def test_read_nonexistent(self, tmp_path):
        img = tmp_path / "missing.jpg"
        assert read_conversations(img) == []

    def test_read_malformed_json(self, tmp_path):
        img = tmp_path / "bad.jpg"
        sidecar = conversation_sidecar_path(img)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text("not valid json", encoding="utf-8")
        assert read_conversations(img) == []

    def test_read_filters_invalid_entries(self, tmp_path):
        img = tmp_path / "partial.jpg"
        sidecar = conversation_sidecar_path(img)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        # Mix valid and invalid entries
        data = [
            {"from": "human", "value": "hello"},
            {"bad": "entry"},  # missing "from" and "value"
            {"from": "gpt", "value": "hi"},
            "not a dict",
        ]
        sidecar.write_text(json.dumps(data), encoding="utf-8")
        result = read_conversations(img)
        assert len(result) == 2
        assert result[0]["value"] == "hello"
        assert result[1]["value"] == "hi"

    def test_write_unicode(self, tmp_path):
        img = tmp_path / "img.png"
        _make_image(img)
        convos = [
            {"from": "human", "value": "<image>\n这张图片有什么缺陷？"},
            {"from": "gpt", "value": "表面有一条划痕缺陷。"},
        ]
        write_conversations(img, convos)
        result = read_conversations(img)
        assert result[0]["value"] == "<image>\n这张图片有什么缺陷？"
        assert result[1]["value"] == "表面有一条划痕缺陷。"

    def test_overwrite(self, tmp_path):
        img = tmp_path / "img.png"
        _make_image(img)
        write_conversations(img, _SIMPLE_CONVOS)
        assert len(read_conversations(img)) == 2
        write_conversations(img, _MULTI_TURN)
        assert len(read_conversations(img)) == 4

    def test_empty_conversations(self, tmp_path):
        img = tmp_path / "img.png"
        _make_image(img)
        write_conversations(img, [])
        result = read_conversations(img)
        assert result == []


# ── SampleSet integration ─────────────────────────────────────────────

class TestSampleSetConversations:
    def test_conversational_count(self, tmp_path):
        ss = _conv_sample_set(tmp_path, [_SIMPLE_CONVOS, [], _MULTI_TURN])
        assert ss.conversational_count == 2

    def test_update_sample_conversations(self, tmp_path):
        ss = _conv_sample_set(tmp_path, [[]])
        img = ss.samples[0].image_path
        new_convos = [{"from": "human", "value": "test"}]
        ss.update_sample(img, conversations=new_convos)
        assert ss.samples[0].conversations == new_convos

    def test_find_sample_with_conversations(self, tmp_path):
        ss = _conv_sample_set(tmp_path, [_MULTI_TURN])
        s = ss.find(ss.samples[0].image_path)
        assert s is not None
        assert len(s.conversations) == 4


# ── Export with conversations ─────────────────────────────────────────

class TestConversationExport:
    def test_llava_uses_conversations(self, tmp_path):
        ss = _conv_sample_set(tmp_path, [_MULTI_TURN])
        out = tmp_path / "export"
        opts = ExportOptions(out_dir=out, copy_images=False, question="")
        export_samples(ss, "llava", opts)
        jsonl = out / "llava_train.jsonl"
        assert jsonl.exists()
        record = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert len(record["conversations"]) == 4
        assert record["conversations"][0]["from"] == "human"
        assert record["conversations"][1]["value"] == "A metal surface with a scratch."

    def test_sharegpt_uses_conversations(self, tmp_path):
        ss = _conv_sample_set(tmp_path, [_SIMPLE_CONVOS])
        out = tmp_path / "export"
        opts = ExportOptions(out_dir=out, copy_images=False, question="")
        export_samples(ss, "sharegpt", opts)
        jsonf = out / "sharegpt_train.json"
        assert jsonf.exists()
        data = json.loads(jsonf.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert len(data[0]["conversations"]) == 2

    def test_swift_uses_caption_from_conversations(self, tmp_path):
        # Swift exports use _sample_answer which falls back to
        # conversations GPT response when caption is empty
        ss = _conv_sample_set(tmp_path, [_SIMPLE_CONVOS])
        out = tmp_path / "export"
        opts = ExportOptions(
            out_dir=out, copy_images=False,
            question="Describe this image.",
        )
        export_samples(ss, "swift", opts)
        jsonl = out / "swift_train.jsonl"
        assert jsonl.exists()
        record = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert record["response"] == "A surface with a crack defect."

    def test_export_prefers_sample_conversations_over_autogen(self, tmp_path):
        """When Sample has conversations, exporter uses them instead of
        auto-generating from regions."""
        ip = tmp_path / "images" / "img.png"
        _make_image(ip)
        custom_convos = [
            {"from": "human", "value": "<image>\nCustom question"},
            {"from": "gpt", "value": "Custom answer"},
        ]
        s = Sample(
            image_path=ip,
            image_width=64, image_height=64,
            category="test",
            conversations=custom_convos,
            regions=[Region(label="defect", shape_type="rectangle")],
            split="train",
        )
        ss = SampleSet(samples=[s])
        out = tmp_path / "export"
        opts = ExportOptions(
            out_dir=out, copy_images=False,
            question="Default question",
        )
        export_samples(ss, "llava", opts)
        jsonl = out / "llava_train.jsonl"
        record = json.loads(jsonl.read_text(encoding="utf-8").strip())
        # Should use custom conversations, not auto-generated
        assert record["conversations"][0]["value"] == "<image>\nCustom question"
        assert record["conversations"][1]["value"] == "Custom answer"


# ── Disk sidecar → Sample round-trip ─────────────────────────────────

class TestSidecarToSample:
    def test_sidecar_written_then_read_into_sample(self, tmp_path):
        """Simulate the full round-trip: save via DetailView signal handler,
        then read back into a fresh Sample."""
        img = tmp_path / "photo.png"
        _make_image(img)

        # 1. Write conversations to disk (as DatasetBrowserView handler does)
        write_conversations(img, _MULTI_TURN)

        # 2. Read back (as DetailView._update_conversations does on re-open)
        disk_convos = read_conversations(img)
        assert len(disk_convos) == 4

        # 3. Attach to a Sample and export
        s = Sample(
            image_path=img,
            image_width=64, image_height=64,
            category="test",
            conversations=disk_convos,
            split="train",
        )
        ss = SampleSet(samples=[s])
        out = tmp_path / "export"
        opts = ExportOptions(out_dir=out, copy_images=False, question="")
        export_samples(ss, "llava", opts)

        jsonl = out / "llava_train.jsonl"
        record = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert len(record["conversations"]) == 4
        assert record["conversations"][2]["from"] == "human"
        assert record["conversations"][3]["from"] == "gpt"

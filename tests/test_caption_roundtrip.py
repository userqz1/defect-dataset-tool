"""Tests for VLM caption round-trip: write → read → export.

Covers: sidecar .txt persistence, SampleSet caption field, and
export through LLaVA / ShareGPT / Swift formats.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from core.annotation_writer import (
    caption_sidecar_path,
    read_caption,
    write_caption,
)
from core.format_out import ExportOptions, export_samples
from core.unified import BBox, Region, Sample, SampleSet


# ── Helpers ────────────────────────────────────────────────────────────

def _make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (100, 150, 200)).save(path)


def _captioned_sample_set(tmp_path: Path,
                          captions: list[str],
                          split: str = "train") -> SampleSet:
    """Build a SampleSet with images on disk and caption fields set."""
    samples = []
    for i, cap in enumerate(captions):
        ip = tmp_path / "images" / f"img_{i:03d}.png"
        _make_image(ip)
        s = Sample(
            image_path=ip,
            image_width=64, image_height=64,
            category="test",
            caption=cap,
            split=split,
        )
        samples.append(s)
    return SampleSet(samples=samples)


# ── Sidecar write / read ─────────────────────────────────────────────

class TestCaptionSidecar:
    def test_write_creates_txt(self, tmp_path):
        img = tmp_path / "photo.jpg"
        _make_image(img)
        p = write_caption(img, "A defective surface with scratches")
        assert p.exists()
        assert p.suffix == ".txt"
        assert p.stem == "photo"
        assert p.read_text(encoding="utf-8") == "A defective surface with scratches"

    def test_read_round_trip(self, tmp_path):
        img = tmp_path / "sample.png"
        _make_image(img)
        write_caption(img, "Two cracks on metal plate")
        assert read_caption(img) == "Two cracks on metal plate"

    def test_read_missing_returns_empty(self, tmp_path):
        img = tmp_path / "no_caption.png"
        assert read_caption(img) == ""

    def test_overwrite(self, tmp_path):
        img = tmp_path / "over.png"
        _make_image(img)
        write_caption(img, "Version 1")
        write_caption(img, "Version 2")
        assert read_caption(img) == "Version 2"

    def test_unicode_caption(self, tmp_path):
        img = tmp_path / "cn.png"
        _make_image(img)
        text = "表面存在两处划伤缺陷，位于中心偏右区域"
        write_caption(img, text)
        assert read_caption(img) == text

    def test_sidecar_path_is_next_to_image(self, tmp_path):
        img = tmp_path / "sub" / "dir" / "file.jpg"
        p = caption_sidecar_path(img)
        assert p == tmp_path / "sub" / "dir" / "file.txt"

    def test_strips_whitespace_on_read(self, tmp_path):
        img = tmp_path / "ws.png"
        _make_image(img)
        sidecar = caption_sidecar_path(img)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text("  padded text  \n\n", encoding="utf-8")
        assert read_caption(img) == "padded text"


# ── SampleSet caption helpers ─────────────────────────────────────────

class TestSampleSetCaptions:
    def test_captioned_count(self, tmp_path):
        ss = _captioned_sample_set(
            tmp_path, ["cap1", "", "cap3"])
        assert ss.captioned_count == 2

    def test_caption_preserved_in_find(self, tmp_path):
        ss = _captioned_sample_set(tmp_path, ["my caption"])
        s = ss.find(ss.samples[0].image_path)
        assert s is not None
        assert s.caption == "my caption"

    def test_update_caption_via_update_sample(self, tmp_path):
        ss = _captioned_sample_set(tmp_path, ["old"])
        ok = ss.update_sample(ss.samples[0].image_path,
                              caption="new caption")
        assert ok
        assert ss.samples[0].caption == "new caption"


# ── LLaVA export ─────────────────────────────────────────────────────

class TestLLaVAExport:
    def test_caption_flows_to_llava(self, tmp_path):
        ss = _captioned_sample_set(
            tmp_path / "data",
            ["Metal surface with pitting defects"],
        )
        out = tmp_path / "export_llava"
        opts = ExportOptions(out_dir=out, copy_images=True)
        result = export_samples(ss, "llava", opts)
        assert result.written_labels == 1

        jsonl = (out / "llava_train.jsonl").read_text(encoding="utf-8")
        rec = json.loads(jsonl.strip().split("\n")[0])
        # Conversation should carry the caption as the gpt response
        gpt_turns = [c for c in rec["conversations"]
                     if c["from"] == "gpt"]
        assert len(gpt_turns) == 1
        assert "Metal surface with pitting defects" in gpt_turns[0]["value"]

    def test_auto_generated_answer_without_caption(self, tmp_path):
        """When no caption is set, export auto-generates from regions."""
        ip = tmp_path / "data" / "images" / "img.png"
        _make_image(ip)
        s = Sample(
            image_path=ip, image_width=64, image_height=64,
            split="train",
            regions=[Region(label="crack", bbox=BBox(0, 0, 30, 30))],
        )
        ss = SampleSet(samples=[s])
        out = tmp_path / "export_llava2"
        result = export_samples(ss, "llava",
                                ExportOptions(out_dir=out, copy_images=True))
        assert result.written_labels == 1
        jsonl = (out / "llava_train.jsonl").read_text(encoding="utf-8")
        rec = json.loads(jsonl.strip())
        gpt_text = [c["value"] for c in rec["conversations"]
                    if c["from"] == "gpt"][0]
        assert "crack" in gpt_text


# ── ShareGPT export ──────────────────────────────────────────────────

class TestShareGPTExport:
    def test_caption_flows_to_sharegpt(self, tmp_path):
        ss = _captioned_sample_set(
            tmp_path / "data",
            ["Surface inspection: no defects found"],
        )
        out = tmp_path / "export_sgpt"
        result = export_samples(ss, "sharegpt",
                                ExportOptions(out_dir=out, copy_images=True))
        assert result.written_labels == 1

        raw = json.loads(
            (out / "sharegpt_train.json").read_text(encoding="utf-8"))
        assert isinstance(raw, list)
        gpt_turn = [c for c in raw[0]["conversations"]
                    if c["from"] == "gpt"][0]
        assert "no defects found" in gpt_turn["value"]

    def test_dataset_info_written(self, tmp_path):
        ss = _captioned_sample_set(tmp_path / "d", ["x"])
        out = tmp_path / "out"
        export_samples(ss, "sharegpt",
                       ExportOptions(out_dir=out, copy_images=True))
        info = json.loads(
            (out / "dataset_info.json").read_text(encoding="utf-8"))
        assert "my_dataset_train" in info


# ── Swift export ──────────────────────────────────────────────────────

class TestSwiftExport:
    def test_caption_flows_to_swift(self, tmp_path):
        ss = _captioned_sample_set(
            tmp_path / "data",
            ["Rust detected on steel beam"],
        )
        out = tmp_path / "export_swift"
        result = export_samples(ss, "swift",
                                ExportOptions(out_dir=out, copy_images=True))
        assert result.written_labels == 1

        jsonl = (out / "swift_train.jsonl").read_text(encoding="utf-8")
        rec = json.loads(jsonl.strip())
        assert "Rust detected on steel beam" in rec["response"]
        assert "images" in rec
        assert len(rec["images"]) == 1


# ── Conversation round-trip ──────────────────────────────────────────

class TestConversationExport:
    def test_custom_conversations_override_auto(self, tmp_path):
        ip = tmp_path / "data" / "images" / "conv.png"
        _make_image(ip)
        s = Sample(
            image_path=ip, image_width=64, image_height=64,
            split="train",
            conversations=[
                {"from": "human", "value": "<image>\nWhat is this?"},
                {"from": "gpt", "value": "A scratched surface."},
            ],
        )
        ss = SampleSet(samples=[s])
        out = tmp_path / "conv_export"
        export_samples(ss, "llava",
                       ExportOptions(out_dir=out, copy_images=True))

        jsonl = (out / "llava_train.jsonl").read_text(encoding="utf-8")
        rec = json.loads(jsonl.strip())
        # Custom conversations preserved verbatim
        assert rec["conversations"][0]["value"] == "<image>\nWhat is this?"
        assert rec["conversations"][1]["value"] == "A scratched surface."

    def test_conversational_count(self, tmp_path):
        ip = tmp_path / "images" / "a.png"
        _make_image(ip)
        s1 = Sample(image_path=ip, conversations=[
            {"from": "human", "value": "Q"},
            {"from": "gpt", "value": "A"},
        ])
        s2 = Sample(image_path=tmp_path / "images" / "b.png")
        _make_image(s2.image_path)
        ss = SampleSet(samples=[s1, s2])
        assert ss.conversational_count == 1

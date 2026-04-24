"""Minimal i18n — string lookup + live language switching.

Intentionally lightweight: a flat ``STRINGS[lang][key]`` dict and a
``t(key)`` lookup. No gettext, no .po/.qm files. Miss → returns the key
unchanged so untranslated UI shows an obvious placeholder ("nav.home")
rather than a blank.

Callers:

- Read strings via ``t("key")`` at *render time* (not at import time).
- When the language flips, the module-level :class:`_LangBus` emits
  :attr:`language_changed`; subscribers are expected to re-render
  their visible text.

Rollout is incremental — coverage starts with nav + Settings popup
and grows file-by-file. Until a string is migrated it stays Chinese.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

_active: str = "zh"


STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        # Navigation rail
        "nav.home": "首页",
        "nav.organize": "整理",
        "nav.browser": "浏览器",
        "nav.settings": "设置",
        # Settings popup
        "settings.title": "设置",
        "settings.theme": "主题",
        "settings.theme.light": "Light",
        "settings.theme.dark": "Dark",
        "settings.language": "语言",
        "settings.language.zh": "中",
        "settings.language.en": "EN",
        "settings.tool_panel": "工具栏",
        "settings.tool_panel.expand": "展开",
        "settings.tool_panel.icon": "图标",
        "settings.catalog": "类别面板",
        "settings.catalog.show": "显示",
        "settings.catalog.hide": "隐藏",
        "settings.cache": "缓存",
        "settings.cache.clear": "清空",
        "settings.cache.cleared": "已清空 {n} 项",
        "settings.cache.read_failed": "读取失败",
        # Project format
        "settings.project_format": "标注格式",
        "settings.project_format.none": "未打开项目",
        # ToolSidebar buttons
        "tools.refresh": "刷新",
        "tools.undo": "撤销",
        "tools.group.analysis": "分析",
        "tools.group.process": "处理",
        "tools.group.output": "输出",
        "tools.group.other": "其他",
        "tools.quality": "质检",
        "tools.dedup": "去重",
        "tools.resize": "缩放",
        "tools.crop": "裁剪",
        "tools.rotate": "旋转",
        "tools.flip": "翻转",
        "tools.convert": "格式转换",
        "tools.augment": "数据增强",
        "tools.predict": "AI 预标注",
        "tools.import_annot": "导入标注",
        "tools.convert_annot": "标注转换",
        "tools.migrate_format": "切换主格式",
        "tools.export": "导出",
        "tools.history": "历史",
        "tools.stats": "统计",
        # Dataset bar
        "ds.empty": "未选择数据集",
        "ds.open_dir": "选择目录",
        "ds.stat.images": "图片",
        "ds.stat.classes": "分类",
        "ds.stat.labeled": "标注",
        "ds.stat.ratio": "最大:最小",
        "ds.stat.flagged": "问题",
        "ds.stat.pending": "待处理",
        "ds.stat.review": "待审核",
        "ds.stat.ready": "就绪",
        "ds.loading": "模型加载中…",
        # Filter chips + bulk buttons
        "filter.all": "全部",
        "filter.labeled": "已标注",
        "filter.unlabeled": "未标注",
        "filter.issues": "有问题",
        "filter.duplicates": "重复",
        "filter.work_new": "待标注",
        "filter.work_review": "待审核",
        "filter.work_fix": "待修补",
        "filter.work_ready": "可导出",
        "filter.search_placeholder": "搜索文件名…",
        # Workflow transition actions
        "wf.submit_review": "提交审核",
        "wf.approve": "通过",
        "wf.reject": "需修补",
        "wf.mark_ready": "标记就绪",
        "wf.batch_done": "已更新 {n} 项状态",
        # VLM / caption
        "vlm.caption": "文本描述",
        "vlm.caption.placeholder": "输入图片描述…",
        "vlm.caption.save": "保存描述",
        # VLM / conversation
        "vlm.conv": "对话",
        "vlm.conv.save": "保存对话",
        "vlm.conv.add": "添加轮次",
        # VLM / region text
        "vlm.region_text": "区域文本",
        "vlm.region_text.save": "保存",
        # Export gating
        "export.scope.all": "导出全部",
        "export.scope.ready": "仅导出已就绪",
        "export.scope.hint": "{ready} 张就绪 / {total} 张总计",
        "filter.multi": "多选",
        "filter.select_all": "全选",
        "filter.unselect_all": "取消全选",
        "filter.delete": "删除",
        # Catalog panel
        "catalog.title": "类别分布 · Class distribution",
        "catalog.subtitle": "CATALOGUE",
        "catalog.section": "类别 · FAULT",
        "catalog.tab.count": "按数量",
        "catalog.tab.name": "按名称",
        "catalog.all": "全部 · All",
        # Distribution chart
        "dist.head": "分布 · DISTRIBUTION",
        # Pager
        "pager.prefix": "第",
        "pager.suffix": "页",
        "pager.total": "共 {n:,} 张",
        "pager.empty": "没有匹配的图片",
        "pager.page_of": "/ {n}",
        # Batch list
        "batch.title": "收件箱 · Inbox",
        "batch.subtitle": "BATCHES",
        "batch.batches": "批次",
        "batch.items": "张",
        "batch.total": "张",
        "batch.empty": "暂无导入批次",
        "batch.import_new": "导入新批次",
        "batch.commit": "提交",
        "batch.status.new": "待处理",
        "batch.status.wip": "进行中",
        "batch.status.ready": "就绪",
        "tools.inbox": "收件箱",
    },
    "en": {
        "nav.home": "Home",
        "nav.organize": "Organize",
        "nav.browser": "Browser",
        "nav.settings": "Settings",
        "settings.title": "Settings",
        "settings.theme": "Theme",
        "settings.theme.light": "Light",
        "settings.theme.dark": "Dark",
        "settings.language": "Language",
        "settings.language.zh": "中",
        "settings.language.en": "EN",
        "settings.tool_panel": "Tool panel",
        "settings.tool_panel.expand": "Expand",
        "settings.tool_panel.icon": "Icons",
        "settings.catalog": "Catalog",
        "settings.catalog.show": "Show",
        "settings.catalog.hide": "Hide",
        "settings.cache": "Cache",
        "settings.cache.clear": "Clear",
        "settings.cache.cleared": "Cleared {n} items",
        "settings.cache.read_failed": "Read failed",
        "settings.project_format": "Format",
        "settings.project_format.none": "No project",
        "tools.refresh": "Refresh",
        "tools.undo": "Undo",
        "tools.group.analysis": "Analysis",
        "tools.group.process": "Process",
        "tools.group.output": "Output",
        "tools.group.other": "Other",
        "tools.quality": "Quality",
        "tools.dedup": "Dedup",
        "tools.resize": "Resize",
        "tools.crop": "Crop",
        "tools.rotate": "Rotate",
        "tools.flip": "Flip",
        "tools.convert": "Convert",
        "tools.augment": "Augment",
        "tools.predict": "AI pre-label",
        "tools.import_annot": "Import Labels",
        "tools.convert_annot": "Convert Labels",
        "tools.migrate_format": "Switch Format",
        "tools.export": "Export",
        "tools.history": "History",
        "tools.stats": "Stats",
        "ds.empty": "No dataset",
        "ds.open_dir": "Open dataset",
        "ds.stat.images": "IMAGES",
        "ds.stat.classes": "CLASSES",
        "ds.stat.labeled": "LABELED",
        "ds.stat.ratio": "MAX:MIN",
        "ds.stat.flagged": "FLAGGED",
        "ds.stat.pending": "PENDING",
        "ds.stat.review": "REVIEW",
        "ds.stat.ready": "READY",
        "ds.loading": "Loading model…",
        "filter.all": "All",
        "filter.labeled": "Labeled",
        "filter.unlabeled": "Unlabeled",
        "filter.issues": "Issues",
        "filter.duplicates": "Duplicates",
        "filter.work_new": "To Label",
        "filter.work_review": "Review",
        "filter.work_fix": "Fix",
        "filter.work_ready": "Export",
        "wf.submit_review": "Submit for Review",
        "wf.approve": "Approve",
        "wf.reject": "Needs Fix",
        "wf.mark_ready": "Mark Ready",
        "wf.batch_done": "Updated {n} items",
        "vlm.caption": "Caption",
        "vlm.caption.placeholder": "Describe this image…",
        "vlm.caption.save": "Save caption",
        "vlm.conv": "Conversation",
        "vlm.conv.save": "Save",
        "vlm.conv.add": "Add turn",
        "vlm.region_text": "Region text",
        "vlm.region_text.save": "Save",
        "export.scope.all": "Export All",
        "export.scope.ready": "Ready Only",
        "export.scope.hint": "{ready} ready / {total} total",
        "filter.search_placeholder": "Search filename…",
        "filter.multi": "Multi",
        "filter.select_all": "Select all",
        "filter.unselect_all": "Clear selection",
        "filter.delete": "Delete",
        "catalog.title": "Class distribution",
        "catalog.subtitle": "CATALOGUE",
        "catalog.section": "FAULT CLASSES",
        "catalog.tab.count": "By count",
        "catalog.tab.name": "By name",
        "catalog.all": "All",
        "dist.head": "DISTRIBUTION",
        "pager.prefix": "Page",
        "pager.suffix": "",
        "pager.total": "{n:,} images",
        "pager.empty": "No matches",
        "pager.page_of": "of {n}",
        "batch.title": "Inbox",
        "batch.subtitle": "BATCHES",
        "batch.batches": "batches",
        "batch.items": "images",
        "batch.total": "images",
        "batch.empty": "No import batches",
        "batch.import_new": "Import batch",
        "batch.commit": "Commit",
        "batch.status.new": "new",
        "batch.status.wip": "wip",
        "batch.status.ready": "ready",
        "tools.inbox": "Inbox",
    },
}


class _LangBus(QObject):
    """Module-level signal emitter. Import `bus` and subscribe to it."""
    language_changed = pyqtSignal(str)


bus = _LangBus()


def lang() -> str:
    return _active


def set_lang(new: str) -> None:
    """Switch the active language and broadcast.

    No-op when the language is already active (avoids needless
    re-render storms if a seg-button is clicked twice).
    """
    global _active
    if new not in STRINGS or new == _active:
        return
    _active = new
    bus.language_changed.emit(new)


def t(key: str, **kwargs) -> str:
    """Look up *key* in the active language dict; fall back to *key*.

    ``kwargs`` are passed to str.format() so callers can use placeholder
    strings like ``t("settings.cache.cleared", n=42)``.
    """
    raw = STRINGS.get(_active, {}).get(key)
    if raw is None:
        return key
    return raw.format(**kwargs) if kwargs else raw

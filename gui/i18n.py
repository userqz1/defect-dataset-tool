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
        # Filter chips + bulk buttons
        "filter.all": "全部",
        "filter.labeled": "已标注",
        "filter.unlabeled": "未标注",
        "filter.issues": "有问题",
        "filter.duplicates": "重复",
        "filter.search_placeholder": "搜索文件名…",
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
        "filter.all": "All",
        "filter.labeled": "Labeled",
        "filter.unlabeled": "Unlabeled",
        "filter.issues": "Issues",
        "filter.duplicates": "Duplicates",
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

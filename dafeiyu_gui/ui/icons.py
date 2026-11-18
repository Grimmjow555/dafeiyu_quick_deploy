"""单色 SVG 图标：按主题颜色着色并缓存。

图标源文件统一是黑色描边；加载后用 ``CompositionMode_SourceIn`` 覆盖成目标
颜色，因此同一份资源可以同时服务浅色和深色主题，不需要准备两套图。
QtSvg 在精简安装里可能缺失，缺了就退化为无图标（按钮照常显示文字）。
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap

try:  # pragma: no cover - 依赖是否完整由运行环境决定
    from PyQt5.QtSvg import QSvgRenderer
except ImportError:  # pragma: no cover
    QSvgRenderer = None  # type: ignore[assignment]

ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"

_ON_PRIMARY = "#FFFFFF"

_current_color = "#5B6675"
_cache: dict[tuple[str, str, int], QIcon] = {}


def set_color(color: str) -> None:
    """记录默认图标颜色；颜色变化时清缓存。"""
    global _current_color
    if color != _current_color:
        _current_color = color
        _cache.clear()


def resolve(color: str | None, colors: dict[str, str]) -> str:
    """把语义色名（如 ``on_primary``）解析成具体颜色值。"""
    if not color:
        return _current_color
    if color == "on_primary":
        return (colors or {}).get("on_primary", _ON_PRIMARY)
    return colors.get(color, color) if colors else color


def icon(name: str, color: str | None = None, size: int = 18) -> QIcon:
    if QSvgRenderer is None:
        return QIcon()
    color = color or _current_color
    key = (name, color, size)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        return QIcon()
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return QIcon()
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    result = QIcon(pixmap)
    _cache[key] = result
    return result


def toggle_icon(name: str, off_color: str, on_color: str, size: int = 18) -> QIcon:
    """给可勾选按钮用：未选中与选中各一种颜色。"""
    result = QIcon()
    for state, color in ((QIcon.Off, off_color), (QIcon.On, on_color)):
        pixmap = icon(name, color, size).pixmap(size, size)
        if not pixmap.isNull():
            result.addPixmap(pixmap, QIcon.Normal, state)
    return result

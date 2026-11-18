"""把 dafeiyu_gui/assets/app.svg 渲染成多尺寸 app.ico。

只在打包 exe 时使用；命令行部署和普通 GUI 运行都不需要这个脚本。
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PyQt5.QtCore import QBuffer, QIODevice, Qt  # noqa: E402
from PyQt5.QtGui import QImage, QPainter  # noqa: E402
from PyQt5.QtSvg import QSvgRenderer  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SVG_PATH = ROOT / "dafeiyu_gui" / "assets" / "app.svg"
ICO_PATH = ROOT / "dafeiyu_gui" / "assets" / "app.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> int:
    if not SVG_PATH.is_file():
        print(f"missing icon source: {SVG_PATH}", file=sys.stderr)
        return 1
    QApplication.instance() or QApplication([])
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        print(f"invalid SVG: {SVG_PATH}", file=sys.stderr)
        return 1
    size = 256
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        print("could not encode PNG", file=sys.stderr)
        return 1
    png = Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")
    png.save(ICO_PATH, format="ICO", sizes=SIZES)
    print(ICO_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

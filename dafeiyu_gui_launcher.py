"""PyInstaller 打包入口：生成单一 .exe 时使用。"""

from dafeiyu_gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())

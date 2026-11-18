"""部署阶段跟踪：把 upload.ps1 / deploy.sh 的输出映射到进度条。"""

from __future__ import annotations

STEP_LABELS: tuple[str, ...] = (
    "准备/校验",
    "上传部署包",
    "环境与镜像",
    "启动服务",
    "掉线守护",
    "导入配置",
    "回填与检查",
)

_MAX_STEP = len(STEP_LABELS) - 1


class StepTracker:
    def __init__(self) -> None:
        self.current = 0
        self.done = False

    def reset(self) -> None:
        self.current = 0
        self.done = False

    def feed(self, line: str) -> int:
        """根据一行原始输出推进阶段；未知行不改变状态，不倒退。"""
        detected = self._match(line)
        if detected is not None:
            self.current = max(self.current, detected)
        return self.current

    def finish(self, success: bool) -> None:
        self.done = success
        if success:
            self.current = _MAX_STEP

    @property
    def percent(self) -> int:
        if self.done:
            return 100
        if _MAX_STEP <= 0:
            return 0
        return int(round(self.current / _MAX_STEP * 100))

    @staticmethod
    def _match(line: str) -> int | None:
        if "Deployment complete" in line or "NapCat/OneBot tokens" in line:
            return 6
        if "[6/6]" in line:
            return 5
        if "[5/6]" in line:
            return 4
        if "[4/6]" in line:
            return 3
        if "[1/6]" in line or "[2/6]" in line or "[3/6]" in line:
            return 2
        if "Upload complete" in line:
            return 1
        if (
            line.startswith("SSH server:")
            or "Reading SSH credentials" in line
            or "First connection" in line
            or "Previously saved host key" in line
            or "The saved key differs" in line
        ):
            return 0
        return None

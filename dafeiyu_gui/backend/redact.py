"""把本地凭证值从界面日志中抹掉。

命令行输出本不应包含密钥，但这里做最后一层兜底：凡是 key.txt 中名字带有
PASSWORD / KEY / TOKEN / WEBHOOK 的非空值，只要长度足够，就在显示、复制、
保存日志之前替换为占位符。原始行只存在于内存，并且不写入磁盘。
"""

from __future__ import annotations

from collections.abc import Mapping

PLACEHOLDER = "<已隐藏>"

_SENSITIVE_HINTS = ("PASSWORD", "KEY", "TOKEN", "WEBHOOK")
_MIN_SECRET_LENGTH = 4


def is_sensitive_field(name: str) -> bool:
    upper = name.upper()
    return any(hint in upper for hint in _SENSITIVE_HINTS)


def sensitive_values(values: Mapping[str, str]) -> list[str]:
    """返回需要从输出中抹掉的值，按长度从长到短排列。"""
    secrets = {
        str(value)
        for name, value in values.items()
        if is_sensitive_field(name) and value and len(str(value)) >= _MIN_SECRET_LENGTH
    }
    return sorted(secrets, key=len, reverse=True)


class Redactor:
    """不可变配置上的字符串脱敏器。"""

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._secrets = sensitive_values(values or {})

    def refresh(self, values: Mapping[str, str]) -> None:
        self._secrets = sensitive_values(values)

    def __bool__(self) -> bool:
        return bool(self._secrets)

    def redact(self, text: str) -> str:
        if not text or not self._secrets:
            return text
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, PLACEHOLDER)
        return text

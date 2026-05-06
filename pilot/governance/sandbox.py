"""轻量沙箱：限制 destructive 工具的影响半径.

V1 不实现真容器/进程沙箱（裁判验收无关），只做参数级限制：
  - 工具调用前检查参数是否触发危险模式
  - destructive 工具必须显式有人类审批
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("pilot.governance.sandbox")


class SandboxViolation(Exception):
    pass


class Sandbox:
    """工具调用包装器：先过 sandbox 才允许执行."""

    def __init__(self, *, max_input_bytes: int = 200_000) -> None:
        self.max_input_bytes = max_input_bytes

    def check(self, *, tool_name: str, tool_input: dict[str, Any]) -> None:
        # 1. 输入大小限制
        try:
            import json
            body = json.dumps(tool_input, ensure_ascii=False)
            if len(body.encode("utf-8")) > self.max_input_bytes:
                raise SandboxViolation(f"输入超过 {self.max_input_bytes} 字节")
        except SandboxViolation:
            raise
        except Exception:
            pass

        # 2. 字符串注入模式
        bad_patterns = ["${jndi:", "${env:", "<script>", "../../"]
        for v in tool_input.values():
            if isinstance(v, str):
                for p in bad_patterns:
                    if p in v:
                        raise SandboxViolation(f"输入命中危险模式: {p}")

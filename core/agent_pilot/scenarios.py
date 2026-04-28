"""Scenario registry covering the six competition scenarios A-F.

Each scenario is a composable unit that can be demonstrated independently
or combined by the Orchestrator. We expose a thin registry so the
dashboard / tests can enumerate available scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class Scenario:
    key: str
    name: str
    description: str
    entry_tools: List[str] = field(default_factory=list)


class ScenarioRegistry:
    _registry: Dict[str, Scenario] = {}

    @classmethod
    def register(cls, scenario: Scenario) -> None:
        cls._registry[scenario.key] = scenario

    @classmethod
    def get(cls, key: str) -> Optional[Scenario]:
        return cls._registry.get(key)

    @classmethod
    def all(cls) -> List[Scenario]:
        return list(cls._registry.values())


# ── Register the 6 default scenarios ──

ScenarioRegistry.register(Scenario(
    key="A_intent",
    name="意图与指令入口",
    description="飞书 IM 群聊/私聊、文本或语音指令，捕捉用户自然语言意图并启动任务。",
    entry_tools=["voice.transcribe", "im.fetch_thread"],
))

ScenarioRegistry.register(Scenario(
    key="B_planner",
    name="任务理解与规划",
    description="Doubao LLM Planner 把用户意图拆成 DAG，支持并行与依赖。",
    entry_tools=[],
))

ScenarioRegistry.register(Scenario(
    key="C_doc_canvas",
    name="文档/白板生成与编辑",
    description="围绕需求自动生成飞书 Docx 和 tldraw/飞书画板内容并可迭代。",
    entry_tools=["doc.create", "doc.append", "canvas.create", "canvas.add_shape"],
))

ScenarioRegistry.register(Scenario(
    key="D_slide",
    name="演示稿生成与排练",
    description="把已沉淀内容结构化为 Slidev PPT，并生成演讲稿支持排练。",
    entry_tools=["slide.generate", "slide.rehearse"],
))

ScenarioRegistry.register(Scenario(
    key="E_sync",
    name="多端协作与一致性",
    description="Yjs CRDT Hub 把 Agent 状态实时同步到移动端/桌面端/Web/飞书。",
    entry_tools=["sync.broadcast"],
))

ScenarioRegistry.register(Scenario(
    key="F_delivery",
    name="总结与交付",
    description="一键打包 Doc + 画布 + PPT + 录音转写，生成飞书分享链接并归档。",
    entry_tools=["archive.bundle"],
))

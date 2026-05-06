"""T1-T20 真机/烟雾测试入口（不发飞书消息，模拟同链路）.

设计哲学:
  - 不能模拟真实飞书事件订阅（需要真 App secret 和云回调），但能跑「IntentRouter → Planner → Orchestrator → 工具」全链路；
  - 用例输入 = 飞书用户文本，断言 = 关键路径属性（intent verdict / plan steps / 是否插 web.search）；
  - LLM_MOCK=1 默认开，避免烧 MiniMax 配额；如要测真 LLM，export AGENT_PILOT_REAL_LLM=1。

输出 result/T20_RESULT.json，给 docs/JUDGE_TEST_REPORT.md 自动填表用。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TestCase:
    tid: str
    category: str
    text: str
    expect_verdict: str  # COMMAND / EXPLICIT / READY / NEEDS_CLARIFY / CHAT
    expect_web_search: bool = False
    notes: str = ""

    # 填充后:
    actual_verdict: str = ""
    actual_steps: list[str] = field(default_factory=list)
    actual_has_web_search: bool = False
    elapsed_ms: int = 0
    pass_: bool = False
    reason: str = ""


CASES: list[TestCase] = [
    TestCase("T1",  "基础响应", "你好",                          "CHAT",            notes="不可沉默"),
    TestCase("T2",  "基础响应", "谢谢",                          "CHAT"),
    TestCase("T3",  "基础响应", "今天天气怎么样",                  "CHAT",            notes="闲聊兜底"),
    TestCase("T4",  "基础响应", "/pilot 帮助",                    "COMMAND",          notes="/pilot 显式命令"),
    TestCase("T5",  "基础响应", "状态",                          "COMMAND"),
    TestCase("T6",  "任务识别", "OpenClaw 三件套",                "READY",            notes="关键字直接命中"),
    TestCase("T7",  "任务识别", "做 8 页 PPT 关于 RAG 系统",      "READY"),
    TestCase("T8",  "任务识别", "帮我做个汇报",                    "NEEDS_CLARIFY",    notes="弱词无主题"),
    TestCase("T9",  "任务识别", "/pilot 测试一下",                "READY",            notes="显式 /pilot"),
    TestCase("T10", "任务识别", "pilot 帮我写文档",               "READY"),
    TestCase("T11", "联网",     "今年最新 AI Agent 进展文档",     "READY", expect_web_search=True),
    TestCase("T12", "联网",     "做关于 2026 RAG 趋势的汇报",     "READY", expect_web_search=True),
    TestCase("T13", "飞书生态", "整理本周群讨论给我做个总结",      "READY",            notes="需 web.search + im.fetch_thread"),
    TestCase("T14", "飞书生态", "用多维表格做月度汇报",           "READY",            notes="需 lark.bitable.search"),
    TestCase("T15", "用户旅程", "三件套 关于公司 H1 战略复盘",   "READY"),
    TestCase("T16", "用户旅程", "做一份产品架构图",              "READY"),
    TestCase("T17", "用户旅程", "@pilot 写文档 + 出 PPT",         "READY"),
    TestCase("T18", "多端",     "/pilot 状态",                    "COMMAND"),
    TestCase("T19", "富媒体",   "[语音输入文本] 做一份周报",      "READY"),
    TestCase("T20", "富媒体",   "把这张图分析一下",               "NEEDS_CLARIFY",    notes="单图需澄清"),
]


async def _run_one(case: TestCase) -> TestCase:
    from pilot.runtime.intent_router import ChatMessage, IntentRouter

    router = IntentRouter()
    t0 = time.perf_counter()
    msg = ChatMessage(sender_open_id="judge_smoke", text=case.text, chat_id="p2p_judge", msg_id=f"m_{case.tid}")
    result = await router.detect([msg], is_p2p=True)
    case.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    case.actual_verdict = result.verdict.name  # 枚举名 (COMMAND/READY/CHAT/...)

    if result.verdict.name == "READY":
        try:
            from pilot.runtime.planner import plan_from_intent

            plan = plan_from_intent(
                case.text,
                meta={"needs_web_search": getattr(result, "needs_web_search", False)},
            )
            case.actual_steps = [s.tool for s in plan.steps]
            case.actual_has_web_search = "web.search" in case.actual_steps
        except Exception as e:
            case.reason = f"planner_error: {e}"

    case.pass_ = case.actual_verdict.upper() == case.expect_verdict.upper()
    if case.expect_web_search and not case.actual_has_web_search:
        case.pass_ = False
        case.reason = (case.reason + ";" if case.reason else "") + "missing web.search"

    return case


async def main() -> int:
    os.environ.setdefault("LLM_MOCK", "1")
    print(f"=== T1-T20 烟雾测试（LLM_MOCK={os.getenv('LLM_MOCK')}）===\n")
    results: list[TestCase] = []
    for c in CASES:
        try:
            r = await _run_one(c)
        except Exception as e:
            c.reason = f"unexpected_error: {e}"
            c.pass_ = False
            r = c
        results.append(r)
        flag = "✓" if r.pass_ else "✗"
        print(f"  {flag} {r.tid:>3}  {r.category:6} {r.actual_verdict:24}  {r.elapsed_ms:>4}ms  {r.text[:30]}{'…' if len(r.text)>30 else ''}")
        if not r.pass_:
            print(f"        ↳ expected={r.expect_verdict}  reason={r.reason or '-'}  steps={r.actual_steps}")

    passed = sum(1 for r in results if r.pass_)
    print(f"\n通过：{passed}/{len(results)}")

    out = Path("data/test_reports/T20_RESULT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            [{
                "tid": r.tid, "category": r.category, "text": r.text,
                "expect_verdict": r.expect_verdict, "actual_verdict": r.actual_verdict,
                "expect_web_search": r.expect_web_search, "actual_has_web_search": r.actual_has_web_search,
                "actual_steps": r.actual_steps,
                "elapsed_ms": r.elapsed_ms, "pass": r.pass_, "reason": r.reason, "notes": r.notes,
            } for r in results], ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"结果写入 {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

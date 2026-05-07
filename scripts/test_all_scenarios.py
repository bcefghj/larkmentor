"""本地端到端真实测试脚本 — 覆盖 PRD 全部场景。

使用真实 MiniMax API，逐一验证比赛要求的 6 个场景 + 加分项。
每个场景独立可运行，带超时控制，输出 PASS/FAIL 报告。

使用: MINIMAX_API_KEY=xxx LLM_MOCK=0 python scripts/test_all_scenarios.py
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("LLM_MOCK", "0")
os.environ.setdefault("DASHBOARD_PUBLIC_BASE", "http://8.136.98.175")

RESULTS: list[tuple[str, bool, str]] = []


def report(scenario: str, passed: bool, detail: str = ""):
    RESULTS.append((scenario, passed, detail))
    status = "\033[32mPASS\033[0m" if passed else "\033[31mFAIL\033[0m"
    print(f"  [{status}] {scenario}: {detail}")


async def test_a_intent():
    """场景A: 意图/指令入口（文本触发）"""
    print("\n=== 场景 A: 意图识别 ===")
    from pilot.llm.client import default_client
    from pilot.llm.safe_json import safe_json_parse

    judge_prompt = (
        "你是飞书办公助手的意图分类器。\n"
        "分类: ready(明确任务)/chat(闲聊)/clarify(任务但信息不够)/not_intent(空)\n"
        '输出JSON: {"verdict":"ready|chat|clarify","task_type":"doc|ppt|canvas|trio|none",'
        '"friendly_reply":"<=40字"}'
    )

    cases = [
        ("你好", "chat"),
        ("帮我写一份关于飞书多维表格的技术报告", "ready"),
        ("做一份 8 页 AI Agent 产品介绍 PPT", "ready"),
        ("帮我做个汇报", "clarify"),
        ("今天天气不错", "chat"),
    ]

    for text, expected in cases:
        try:
            resp = await asyncio.wait_for(
                default_client().chat(
                    system=judge_prompt,
                    messages=[{"role": "user", "content": f"用户说: {text}"}],
                    temperature=0.0,
                    max_tokens=200,
                    response_format={"type": "json_object"},
                ),
                timeout=15.0,
            )
            obj = safe_json_parse(resp.get("text", ""), expected_type=dict) or {}
            verdict = obj.get("verdict", "error")
            ok = verdict == expected
            report(f"A-意图「{text}」", ok, f"期望={expected} 实际={verdict}")
        except Exception as e:
            report(f"A-意图「{text}」", False, f"异常: {e}")


async def test_b_planner():
    """场景B: 任务理解与规划"""
    print("\n=== 场景 B: Planner 大纲 ===")
    from pilot.agents.planner import PlannerAgent

    agent = PlannerAgent()
    state = {
        "intent": "帮我写一份飞书 AI 助手在校园场景的应用方案",
        "task_type": "doc",
        "outline": [],
    }

    try:
        state = await asyncio.wait_for(agent.execute(state), timeout=30.0)
        outline = state.get("outline", [])
        n_sections = len(outline)
        first_heading = outline[0].get("heading", "") if outline else ""

        report("B-章节数>=5", n_sections >= 5, f"实际={n_sections}")
        report("B-标题相关性", "飞书" in first_heading or "AI" in first_heading or "校园" in first_heading,
               f"首章=「{first_heading}」")
        has_points = all(len(s.get("key_points", [])) >= 2 for s in outline[:3])
        report("B-要点>=2/章", has_points, f"前3章要点数={[len(s.get('key_points',[])) for s in outline[:3]]}")
    except Exception as e:
        report("B-Planner", False, f"异常: {e}")


async def test_c_doc():
    """场景C: 文档生成端到端"""
    print("\n=== 场景 C: 文档生成 ===")
    from pilot.agents.planner import PlannerAgent
    from pilot.agents.researcher import ResearchAgent
    from pilot.agents.writer import WriterAgent

    planner = PlannerAgent()
    researcher = ResearchAgent()
    writer = WriterAgent()

    state = {
        "intent": "帮我写一份关于 Multi-Agent 协作系统的技术文档",
        "task_type": "doc",
        "outline": [],
        "research_results": [],
        "draft_sections": [],
    }

    try:
        state = await asyncio.wait_for(planner.execute(state), timeout=30.0)
        state = await asyncio.wait_for(researcher.execute(state), timeout=60.0)
        state = await asyncio.wait_for(writer.execute(state), timeout=90.0)

        sections = state.get("draft_sections", [])
        total_chars = sum(len(s.get("content", "")) for s in sections)
        has_citation = any("[" in s.get("content", "") for s in sections)
        has_tool_call = any("[TOOL_CALL]" in s.get("content", "") for s in sections)

        report("C-总字数>=1500", total_chars >= 1500, f"实际={total_chars}字")
        report("C-有引用标注", has_citation, "检查[1][2]等脚注")
        report("C-无TOOL_CALL泄漏", not has_tool_call, "文本中不含[TOOL_CALL]")
        report("C-章节数匹配", len(sections) == len(state.get("outline", [])),
               f"sections={len(sections)} outline={len(state.get('outline', []))}")
    except Exception as e:
        report("C-文档生成", False, f"异常: {e}")


async def test_d_ppt():
    """场景D: PPT 生成"""
    print("\n=== 场景 D: PPT 生成 ===")
    from pilot.capability.tools.slide import slide_generate

    try:
        result = await asyncio.wait_for(
            slide_generate(
                title="AI Agent 技术趋势 2026",
                intent="做一份关于 AI Agent 最新发展的 PPT",
                pages=8,
            ),
            timeout=60.0,
        )
        pages = result.get("pages", 0)
        pptx_path = result.get("pptx_path", "")
        has_file = os.path.exists(pptx_path) if pptx_path else False

        report("D-页数>=6", pages >= 6, f"实际={pages}页")
        report("D-pptx文件存在", has_file, pptx_path[-40:] if pptx_path else "无路径")
        report("D-有slide_id", bool(result.get("slide_id")), result.get("slide_id", "")[:20])
    except Exception as e:
        report("D-PPT生成", False, f"异常: {e}")


async def test_f_delivery():
    """场景F: 交付卡片格式验证"""
    print("\n=== 场景 F: 交付卡片 ===")
    from pilot.surface.feishu.cards import task_delivered_card

    card = task_delivered_card(
        task_id="plan_20260507_083000_test",
        title="AI Agent 技术报告",
        artifacts=[
            {"kind": "doc", "title": "技术报告", "url": "http://example.com/doc"},
            {"kind": "slide", "title": "演示稿", "url": "http://example.com/ppt"},
        ],
        summary="已完成技术报告，含6章2100字，引用Gartner和IDC最新数据。",
        elapsed_sec=120,
        iterations=2,
    )

    has_header = card.get("header", {}).get("template") == "green"
    has_note = any(e.get("tag") == "note" for e in card.get("elements", []))
    has_actions = any(e.get("tag") == "action" for e in card.get("elements", []))
    elements_text = str(card.get("elements", []))
    has_summary = "已完成技术报告" in elements_text
    has_elapsed = "2m0s" in elements_text or "耗时" in elements_text

    report("F-绿色标题", has_header, f"template={card.get('header',{}).get('template')}")
    report("F-有备注区(耗时)", has_note, "note tag存在")
    report("F-有按钮组", has_actions, "action tag存在")
    report("F-含摘要", has_summary, "摘要文本存在")
    report("F-含耗时", has_elapsed, "耗时信息存在")


async def test_clarify():
    """加分项: 模糊意图主动澄清"""
    print("\n=== 加分: 主动澄清 ===")
    from pilot.llm.client import default_client
    from pilot.llm.safe_json import safe_json_parse

    judge_prompt = (
        "你是飞书办公助手的意图分类器。\n"
        "分类: ready/chat/clarify/not_intent\n"
        'JSON: {"verdict":"...","missing":["缺什么信息"],"friendly_reply":"澄清引导语"}'
    )

    cases = [
        ("帮我做个汇报", "clarify"),
        ("整理一下", "clarify"),
    ]

    for text, expected in cases:
        try:
            resp = await asyncio.wait_for(
                default_client().chat(
                    system=judge_prompt,
                    messages=[{"role": "user", "content": f"用户说: {text}"}],
                    temperature=0.0, max_tokens=200,
                    response_format={"type": "json_object"},
                ),
                timeout=15.0,
            )
            obj = safe_json_parse(resp.get("text", ""), expected_type=dict) or {}
            verdict = obj.get("verdict", "")
            missing = obj.get("missing", [])
            report(f"澄清「{text}」", verdict == expected, f"verdict={verdict} missing={missing}")
        except Exception as e:
            report(f"澄清「{text}」", False, f"异常: {e}")


async def main():
    print("=" * 60)
    print("Agent-Pilot PRD 全场景真实测试")
    print(f"API Key: ...{os.getenv('MINIMAX_API_KEY', '')[-8:]}")
    print(f"Mock: {os.getenv('LLM_MOCK', '?')}")
    print("=" * 60)

    t0 = time.time()

    await test_a_intent()
    await test_b_planner()
    await test_c_doc()
    await test_d_ppt()
    await test_f_delivery()
    await test_clarify()

    elapsed = time.time() - t0

    print("\n" + "=" * 60)
    print(f"测试完成 · 耗时 {elapsed:.0f}s")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"结果: {passed}/{total} 通过")

    if passed < total:
        print("\n失败项:")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  ❌ {name}: {detail}")

    print("=" * 60)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())

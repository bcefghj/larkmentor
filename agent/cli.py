"""CLI Entry · python -m agent [chat|plan|pilot|status|demo]

Provides a local TUI interface for testing Agent-Pilot without Feishu Bot.
"""

from __future__ import annotations

import argparse
import json


def cmd_chat(args) -> None:
    """Interactive chat loop using the Pilot service."""
    from core.agent_pilot.service import launch

    print("Agent-Pilot v10 CLI (输入 /quit 退出)")
    print()
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text in ("/quit", "/exit", ":q"):
            break
        if not text:
            continue
        try:
            result = launch(text, user_open_id="cli_user")
            if isinstance(result, dict):
                print(f"\nbot> Plan: {result.get('plan_id', 'N/A')}")
                print(f"     Steps: {result.get('step_count', 0)}")
                print(f"     Status: {result.get('verdict', 'unknown')}\n")
            else:
                print(f"\nbot> {result}\n")
        except Exception as e:
            print(f"\n[error] {e}\n")


def cmd_status(args) -> None:
    """Show system status."""
    from config import Config

    status = {
        "version": "10.0.0",
        "feishu_app_id": Config.FEISHU_APP_ID[:8] + "..." if Config.FEISHU_APP_ID else "(not set)",
        "ark_model": Config.ARK_MODEL,
        "dashboard_port": Config.DASHBOARD_PORT,
    }
    try:
        from agent.providers import default_providers
        status["providers"] = default_providers().snapshot()
    except Exception:
        status["providers"] = "unavailable"
    try:
        from agent.tools import get_registry
        status["tools_registered"] = len(get_registry())
    except Exception:
        status["tools_registered"] = "unavailable"

    print(json.dumps(status, ensure_ascii=False, indent=2, default=str))


def cmd_plan(args) -> None:
    """Plan mode: decompose intent into DAG without executing."""
    from core.agent_pilot.planner import plan_from_intent

    intent = " ".join(args.intent)
    plan = plan_from_intent(intent, user_open_id="cli")
    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))


def cmd_pilot(args) -> None:
    """Run full Agent-Pilot pipeline."""
    from core.agent_pilot.service import launch

    intent = " ".join(args.intent)
    result = launch(intent, user_open_id="cli")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def cmd_demo(args) -> None:
    """Run a demo scenario to showcase the full pipeline."""
    import os
    os.environ["AGENT_PILOT_DEMO_MODE"] = "1"

    from core.agent_pilot.planner import plan_from_intent

    scenarios = [
        "把本周的产品讨论整理成方案文档 + 评审 PPT",
        "帮我做一个季度复盘演示，包含数据可视化",
        "根据群聊讨论生成项目启动文档",
    ]
    scenario = scenarios[0] if not args.intent else " ".join(args.intent)
    print(f"[Demo] 场景: {scenario}")
    print()

    plan = plan_from_intent(scenario, user_open_id="demo_user")
    print(f"[Demo] 计划 ID: {plan.plan_id}")
    print(f"[Demo] 步骤数: {len(plan.steps)}")
    print()
    for i, step in enumerate(plan.steps, 1):
        deps = f" (依赖: {', '.join(step.depends_on)})" if step.depends_on else ""
        print(f"  {i}. [{step.tool}] {step.description}{deps}")
    print()
    print("[Demo] 完成 — 使用 `python -m agent pilot <意图>` 执行完整流程")


def cmd_mcp(args) -> None:
    """Show MCP servers status."""
    try:
        from agent import default_mcp_manager
        mgr = default_mcp_manager()
        mgr.start()
        print(json.dumps(mgr.snapshot(), ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"MCP unavailable: {e}")


def cmd_skills(args) -> None:
    """List loaded Skills."""
    try:
        from agent import default_skills_loader
        loader = default_skills_loader()
        print(f"Loaded {len(loader.skills)} skills:")
        for name, s in loader.skills.items():
            print(f"  [{s.source}] {name}: {s.description[:80]}")
    except Exception as e:
        print(f"Skills unavailable: {e}")


def cmd_learner(args) -> None:
    """Show learning loop stats."""
    try:
        from agent.learner import default_learner
        print(json.dumps(default_learner().stats(), ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Learner unavailable: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-pilot", description="Agent-Pilot v10 CLI")
    parser.add_argument("--tenant", default="default", help="Tenant ID")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("chat", help="Interactive chat REPL").set_defaults(func=cmd_chat)
    sub.add_parser("status", help="Show system status").set_defaults(func=cmd_status)
    sub.add_parser("mcp", help="Show MCP servers status").set_defaults(func=cmd_mcp)
    sub.add_parser("skills", help="List loaded Skills").set_defaults(func=cmd_skills)
    sub.add_parser("learner", help="Show learning loop stats").set_defaults(func=cmd_learner)
    sub.add_parser("demo", help="Run demo scenario").add_argument("intent", nargs="*")
    sub._group_actions[-1].set_defaults(func=cmd_demo)

    p_plan = sub.add_parser("plan", help="Plan mode (no execution)")
    p_plan.add_argument("intent", nargs="+")
    p_plan.set_defaults(func=cmd_plan)

    p_pilot = sub.add_parser("pilot", help="Run full Agent-Pilot")
    p_pilot.add_argument("intent", nargs="+")
    p_pilot.set_defaults(func=cmd_pilot)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

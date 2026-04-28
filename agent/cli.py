"""CLI Entry · python -m larkmentor chat

Hermes Agent 启发 - 本地 TUI 对话，不必经过飞书 Bot。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict


def cmd_chat(args) -> None:
    """Interactive chat loop."""
    from bot.handlers_v4 import handle_message
    print("🤖 LarkMentor v4 CLI (输入 /quit 退出, /help 查看命令)")
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
        result = handle_message(
            text=text, user_open_id="cli_user", chat_id="cli_chat",
            chat_type="p2p", tenant_id=args.tenant,
        )
        if isinstance(result, dict):
            reply = result.get("reply", "")
            print(f"\nbot> {reply}\n")
        else:
            print(f"\nbot> {result}\n")


def cmd_status(args) -> None:
    """Show system status."""
    from agent import (
        default_context_manager, default_memory, default_permission_gate,
        default_skills_loader, default_mcp_manager,
    )
    from agent.tools import get_registry
    from agent.providers import default_providers
    from agent.named_agents import default_named_agents
    status = {
        "providers": default_providers().snapshot(),
        "memory": default_memory().snapshot(),
        "context": default_context_manager().snapshot(),
        "permissions": default_permission_gate().snapshot(),
        "skills_loaded": len(default_skills_loader().skills),
        "tools_registered": len(get_registry()),
        "mcp": default_mcp_manager().snapshot(),
        "named_agents": default_named_agents().list_names(),
    }
    print(json.dumps(status, ensure_ascii=False, indent=2, default=str))


def cmd_plan(args) -> None:
    from bot.handlers_v4 import _cmd_plan
    result = _cmd_plan(" ".join(args.intent), user_open_id="cli", tenant_id=args.tenant)
    print(result.get("reply", ""))


def cmd_pilot(args) -> None:
    from bot.handlers_v4 import _run_pilot
    task = " ".join(args.intent)
    result = _run_pilot(task, user_open_id="cli", chat_id="cli_chat", tenant_id=args.tenant)
    print(result.get("reply", ""))


def cmd_mcp(args) -> None:
    from agent import default_mcp_manager
    mgr = default_mcp_manager()
    mgr.start()
    print(json.dumps(mgr.snapshot(), ensure_ascii=False, indent=2))


def cmd_skills(args) -> None:
    from agent import default_skills_loader
    loader = default_skills_loader()
    print(f"Loaded {len(loader.skills)} skills:")
    for name, s in loader.skills.items():
        print(f"  [{s.source}] {name}: {s.description[:80]}")


def cmd_learner(args) -> None:
    from agent.learner import default_learner
    print(json.dumps(default_learner().stats(), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="larkmentor", description="LarkMentor v4 CLI")
    parser.add_argument("--tenant", default="default", help="Tenant ID")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("chat", help="Interactive chat REPL").set_defaults(func=cmd_chat)
    sub.add_parser("status", help="Show system status").set_defaults(func=cmd_status)
    sub.add_parser("mcp", help="Show MCP servers status").set_defaults(func=cmd_mcp)
    sub.add_parser("skills", help="List loaded Skills").set_defaults(func=cmd_skills)
    sub.add_parser("learner", help="Show learning loop stats").set_defaults(func=cmd_learner)

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

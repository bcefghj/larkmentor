"""LarkMentor v4 IM handlers · 统一入口（取代旧 event_handler.py 三座分叉）

核心原则：
- 所有自然语言 → intent_router（LLM 短判）→ Named Agent → agent.loop.run
- 保留 4 个评委指令：/context /plan /skills /mcp
- 新增 3 个 v4 命令：/swarm /quality /model
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.handlers_v4")


# ── Intent classification ──


def classify_intent(text: str) -> Dict[str, Any]:
    """LLM 短判意图类别。"""
    text_stripped = (text or "").strip()
    if not text_stripped:
        return {"kind": "empty", "team": None}

    # Explicit commands
    if text_stripped.startswith("/"):
        parts = text_stripped.split(None, 1)
        cmd = parts[0][1:]
        args = parts[1] if len(parts) > 1 else ""
        return {"kind": "command", "command": cmd, "args": args}

    # @-addressed named agent
    m = re.match(r'^@(\w+)\s+(.+)$', text_stripped, re.DOTALL)
    if m:
        return {"kind": "named_agent", "agent": m.group(1), "task": m.group(2)}

    # Keyword-based quick routing
    text_lower = text_stripped.lower()

    # Pilot indicators
    pilot_kws = ["pilot", "方案", "文档", "ppt", "演示", "整理", "做个", "做一份",
                 "生成", "规划", "闭环", "汇报"]
    if any(kw in text_lower for kw in pilot_kws):
        return {"kind": "pilot", "team": "pilot", "task": text_stripped}

    # Mentor indicators
    mentor_kws = ["起草", "回复", "怎么说", "周报", "如何表达", "新人", "清单"]
    if any(kw in text_lower for kw in mentor_kws):
        return {"kind": "mentor", "team": "mentor", "task": text_stripped}

    # Default: chat
    return {"kind": "chat", "team": None, "task": text_stripped}


# ── Handler entry (called from event_handler wrapper) ──


def handle_message(
    *, text: str, user_open_id: str = "",
    chat_id: str = "", chat_type: str = "p2p",
    sender_name: str = "", sender_id: str = "",
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Main entry: unified message handler v4."""
    intent = classify_intent(text)
    kind = intent.get("kind", "chat")

    if kind == "empty":
        return {"ok": True, "reply": "请输入消息内容。"}

    # Dispatch by kind
    if kind == "command":
        return _handle_command(intent, user_open_id=user_open_id, chat_id=chat_id, tenant_id=tenant_id)
    elif kind == "named_agent":
        return _run_named_agent(intent["agent"], intent["task"], user_open_id=user_open_id, tenant_id=tenant_id)
    elif kind == "pilot":
        return _run_pilot(intent["task"], user_open_id=user_open_id, chat_id=chat_id, tenant_id=tenant_id)
    elif kind == "mentor":
        return _run_mentor(intent["task"], user_open_id=user_open_id, tenant_id=tenant_id)
    else:
        return _run_chat(text, user_open_id=user_open_id, tenant_id=tenant_id)


def _handle_command(intent: Dict, *, user_open_id: str, chat_id: str, tenant_id: str) -> Dict[str, Any]:
    cmd = intent["command"]
    args = intent["args"]
    try:
        if cmd == "context":
            return _cmd_context()
        elif cmd == "plan":
            return _cmd_plan(args, user_open_id=user_open_id, tenant_id=tenant_id)
        elif cmd == "skills":
            return _cmd_skills()
        elif cmd == "mcp":
            return _cmd_mcp()
        elif cmd == "swarm":
            return _cmd_swarm(args, user_open_id=user_open_id, tenant_id=tenant_id)
        elif cmd == "quality":
            return _cmd_quality(args)
        elif cmd == "model":
            return _cmd_model(args)
        elif cmd == "pilot":
            return _run_pilot(args, user_open_id=user_open_id, chat_id=chat_id, tenant_id=tenant_id)
        elif cmd == "help":
            return _cmd_help()
        else:
            return {"ok": True, "reply": f"未知命令 /{cmd}，发送 /help 看帮助"}
    except Exception as e:
        logger.exception("command /%s failed", cmd)
        return {"ok": False, "reply": f"命令执行失败：{e}"}


def _cmd_help() -> Dict[str, Any]:
    text = """**LarkMentor v4 命令列表**

- `/pilot <意图>` — 启动 Agent-Pilot 全链路（IM→Doc→Canvas→Slides→归档）
- `/plan <意图>` — Plan Mode，只生成规划不执行
- `/context` — 查看 5 层压缩、token 预算、记忆层状态
- `/skills` — 列出已挂载 Skills（官方 + 自研 + 用户生成）
- `/mcp` — 查看 MCP 连接状态（本地 stdio + 远程 HTTP）
- `/swarm <话题>` — 召唤多 agent 团队辩论并收敛
- `/quality <plan_id>` — 查看 5 Quality Gates 审查得分
- `/model <doubao|minimax|deepseek|kimi>` — 切换当前会话的默认模型
- `@agent_name <task>` — 直接指定某个命名 agent（pilot/shield/mentor/debater/researcher）
"""
    return {"ok": True, "reply": text, "kind": "help"}


def _cmd_context() -> Dict[str, Any]:
    from agent import default_context_manager, default_memory, default_permission_gate
    snap = {
        "context_compression": default_context_manager().snapshot(),
        "memory": default_memory().snapshot(),
        "permissions": default_permission_gate().snapshot(),
    }
    return {"ok": True, "reply": "```json\n" + json.dumps(snap, ensure_ascii=False, indent=2)[:3000] + "\n```", "data": snap}


def _cmd_plan(intent_text: str, *, user_open_id: str, tenant_id: str) -> Dict[str, Any]:
    """Plan Mode: 只生成规划，不真执行工具。"""
    if not intent_text:
        return {"ok": True, "reply": "用法: /plan <描述你的意图>"}
    from agent.router import default_router
    dec = default_router().route(intent_text)
    from agent.orchestrator_worker import default_orchestrator_worker
    # Just run lead plan, don't spawn workers
    providers = __import__('agent.providers', fromlist=['default_providers']).default_providers()
    prompt = (
        f"规划模式（不执行）：请把下面的意图分解成 JSON 步骤，不真调工具。\n\n"
        f"意图：{intent_text}\n\n"
        f"推荐策略：{dec.strategy.value}（复杂度 {dec.complexity:.2f}）\n"
        f"推荐团队：{', '.join(dec.recommended_agents)}\n\n"
        f'返回 JSON：{{"strategy": "...", "steps": [...]}}'
    )
    out = providers.chat(messages=[{"role": "user", "content": prompt}], task_kind="planning", max_tokens=1500)
    return {"ok": True, "reply": out, "kind": "plan_only", "strategy": dec.strategy.value}


def _cmd_skills() -> Dict[str, Any]:
    from agent import default_skills_loader
    from agent.tools import get_registry
    loader = default_skills_loader()
    tools = get_registry()
    summary = {
        "skills": loader.snapshot(),
        "tools": {name: m.description[:80] for name, m in tools.items()},
        "counts": {
            "total_skills": len(loader.skills),
            "total_tools": len(tools),
            "skills_by_source": {
                "official": sum(1 for s in loader.skills.values() if s.source == "official"),
                "builtin": sum(1 for s in loader.skills.values() if s.source == "builtin"),
                "user_generated": sum(1 for s in loader.skills.values() if s.source == "user_generated"),
            },
        },
    }
    return {"ok": True, "reply": json.dumps(summary["counts"], ensure_ascii=False, indent=2), "data": summary}


def _cmd_mcp() -> Dict[str, Any]:
    from agent import default_mcp_manager
    mgr = default_mcp_manager()
    if not mgr._started:
        mgr.start()
    snap = mgr.snapshot()
    return {"ok": True, "reply": json.dumps(snap, ensure_ascii=False, indent=2)[:3000], "data": snap}


def _cmd_swarm(topic: str, *, user_open_id: str, tenant_id: str) -> Dict[str, Any]:
    """多 agent 辩论并收敛。"""
    if not topic:
        return {"ok": True, "reply": "用法: /swarm <话题>"}
    from agent.patterns.debate import debate_round
    from agent.providers import default_providers
    providers = default_providers()

    def _doubao(p): return providers.chat([{"role": "user", "content": p}], task_kind="chinese_chat", max_tokens=800)
    def _minimax(p): return providers.chat([{"role": "user", "content": p}], task_kind="reasoning", max_tokens=800)
    def _deepseek(p): return providers.chat([{"role": "user", "content": p}], task_kind="summary", max_tokens=800)
    def _judge(p): return providers.chat([{"role": "user", "content": p}], task_kind="validation", max_tokens=600)

    result = debate_round(topic, llm_doubao=_doubao, llm_minimax=_minimax, llm_deepseek=_deepseek, llm_judge=_judge)
    return {"ok": True, "reply": f"[{result['rounds']} 轮辩论收敛]\n\n{result['answer']}", "data": result}


def _cmd_quality(plan_id: str) -> Dict[str, Any]:
    from agent.validators import default_quality_gates
    runner = default_quality_gates()
    # Get last plan output from data
    try:
        from pathlib import Path
        plans_dir = Path("data/pilot_plans")
        candidates = sorted(plans_dir.glob(f"*{plan_id}*.json") if plan_id else plans_dir.glob("*.json"),
                            key=lambda p: p.stat().st_mtime, reverse=True)[:1]
        if not candidates:
            return {"ok": True, "reply": "未找到 plan，先跑 /pilot <任务>"}
        content = candidates[0].read_text()
    except Exception as e:
        content = plan_id
    report = runner.run(content)
    return {"ok": True, "reply": json.dumps(report.as_dict(), ensure_ascii=False, indent=2), "data": report.as_dict()}


def _cmd_model(model: str) -> Dict[str, Any]:
    from agent.providers import default_providers
    providers = default_providers()
    if not model:
        return {"ok": True, "reply": json.dumps(providers.snapshot()["providers"], ensure_ascii=False, indent=2)}
    if model not in providers.configs:
        return {"ok": True, "reply": f"未知模型: {model}。可选: {list(providers.configs.keys())}"}
    # Update routing default
    providers.routing["default"] = model
    providers.routing["chinese_chat"] = model
    return {"ok": True, "reply": f"已切换默认模型 → {model} ({providers.configs[model].model})"}


# ── Agent dispatchers ──


def _run_pilot(task: str, *, user_open_id: str, chat_id: str, tenant_id: str) -> Dict[str, Any]:
    """场景 A→B→C→D→F 组合编排 via Orchestrator-Worker."""
    from agent.orchestrator_worker import default_orchestrator_worker
    ow = default_orchestrator_worker()
    providers = __import__('agent.providers', fromlist=['default_providers']).default_providers()
    providers.reset_plan_budget()
    result = ow.sync_run(task, team="pilot", extra_context={
        "user_open_id": user_open_id, "chat_id": chat_id, "tenant_id": tenant_id,
    })
    return {
        "ok": result.ok,
        "reply": result.final_synthesis or "（编排完成，查看 /dashboard）",
        "data": {
            "workers": [{"type": w.agent_type, "status": w.status, "ms": w.duration_ms} for w in result.worker_results],
            "cost_cny": result.cost_cny,
            "tokens": result.tokens_used,
        },
    }


def _run_named_agent(agent_name: str, task: str, *, user_open_id: str, tenant_id: str) -> Dict[str, Any]:
    from agent.named_agents import default_named_agents
    registry = default_named_agents()
    agent = registry.get(agent_name)
    if not agent:
        return {"ok": False, "reply": f"未找到 agent: @{agent_name}。可选: {registry.list_names()}"}
    from agent.providers import default_providers
    out = default_providers().chat(
        messages=[
            {"role": "system", "content": agent.instruction},
            {"role": "user", "content": task},
        ],
        task_kind=agent.model_kind,
        max_tokens=1800,
    )
    return {"ok": True, "reply": out, "agent": agent_name}


def _run_mentor(task: str, *, user_open_id: str, tenant_id: str) -> Dict[str, Any]:
    return _run_named_agent("mentor", task, user_open_id=user_open_id, tenant_id=tenant_id)


def _run_chat(text: str, *, user_open_id: str, tenant_id: str) -> Dict[str, Any]:
    from agent.providers import default_providers
    out = default_providers().chat(
        messages=[
            {"role": "system", "content": "你是 LarkMentor，一个对标 Claude Code 的办公协同 AI。"},
            {"role": "user", "content": text},
        ],
        task_kind="chinese_chat",
        max_tokens=1000,
    )
    return {"ok": True, "reply": out}

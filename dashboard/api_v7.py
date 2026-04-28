"""Dashboard v7 · 三视角 API + 静态视图路由.

暴露：
- ``GET /api/v7/tasks``                   Pilot 任务列表（PRD §8）
- ``GET /api/v7/tasks/{task_id}``         任务详情 + Agent 日志
- ``GET /api/v7/tasks/{task_id}/timeline`` 状态机转移历史 + domain events
- ``GET /api/v7/skills``                  PilotLearner 自动生成的 SKILL
- ``GET /api/v7/triad``                   三线协同雷达数据
- ``GET /api/v7/memory/{tenant}``         6 级 Memory 内容（评委可视化）
- ``GET /api/v7/intent_stats``            主动识别命中统计

提供 3 个静态页面：
- ``/v7/pilot``      Pilot 主驾驶舱（任务列表 / 详情 / Agent 日志）
- ``/v7/memory``     6 级 Memory 时间线
- ``/v7/triad``      三线协同雷达
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dashboard.api_v7")


def _safe_json_load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _list_tasks(limit: int = 50) -> List[Dict[str, Any]]:
    """从 default_task_service 列任务（实时）+ 磁盘回看（历史）."""
    out: List[Dict[str, Any]] = []
    try:
        from core.agent_pilot.application import default_task_service
        svc = default_task_service()
        for t in svc.list_live():
            out.append({
                "task_id": t.task_id,
                "title": t.title,
                "intent": t.intent[:120],
                "state": t.state.value,
                "owner": t.owner_lock.owner_open_id,
                "created_ts": t.created_ts,
                "updated_ts": t.updated_ts,
                "artifacts_count": len(t.artifacts),
                "agent_logs_count": len(t.agent_logs),
                "transitions_count": len(t.transitions),
                "source_chat_id": t.source_chat_id,
            })
    except Exception as e:
        logger.debug("list live tasks failed: %s", e)

    # 历史（仅展示元数据）
    try:
        from core.agent_pilot.application import default_task_service
        rows = default_task_service().repo.list(limit=limit)
        seen = {x["task_id"] for x in out}
        for r in rows:
            if r.get("task_id") in seen:
                continue
            out.append({
                "task_id": r.get("task_id"),
                "title": r.get("title") or "",
                "intent": (r.get("intent") or "")[:120],
                "state": r.get("state") or "delivered",
                "owner": (r.get("owner_lock") or {}).get("owner_open_id", ""),
                "created_ts": r.get("created_ts", 0),
                "updated_ts": r.get("updated_ts", 0),
                "artifacts_count": len(r.get("artifacts", [])),
                "agent_logs_count": len(r.get("agent_logs", [])),
                "transitions_count": len(r.get("transitions", [])),
                "source_chat_id": r.get("source_chat_id", ""),
            })
    except Exception:
        pass

    out.sort(key=lambda x: x.get("updated_ts", 0), reverse=True)
    return out[:limit]


def _task_detail(task_id: str) -> Optional[Dict[str, Any]]:
    try:
        from core.agent_pilot.application import default_task_service
        t = default_task_service().get(task_id)
        if t is not None:
            return t.to_dict()
        # disk fallback
        rows = default_task_service().repo.list(limit=200)
        for r in rows:
            if r.get("task_id") == task_id:
                return r
    except Exception as e:
        logger.debug("task_detail failed: %s", e)
    return None


def _list_skills() -> List[Dict[str, Any]]:
    try:
        from core.agent_pilot.application import default_pilot_learner
        out = []
        for sk in default_pilot_learner().list_skills():
            out.append({
                "skill_id": sk.skill_id,
                "title": sk.title,
                "description": sk.description,
                "intent_pattern": sk.intent_pattern[:140],
                "examples": sk.examples[:3],
                "created_ts": sk.created_ts,
                "hit_count": sk.hit_count,
                "md_path": sk.md_path,
            })
        return out
    except Exception as e:
        logger.debug("list_skills failed: %s", e)
        return []


def _triad_data() -> Dict[str, Any]:
    """三线协同雷达：Shield + Mentor + Pilot 各自指标."""
    out = {
        "shield": {"intercepted": 0, "p0_p1_alerts": 0, "label": "消息守护"},
        "mentor": {"drafts": 0, "skills_used": 0, "label": "表达带教"},
        "pilot": {"tasks_total": 0, "tasks_delivered": 0,
                   "skills_auto": 0, "label": "主驾驶"},
    }
    # shield
    try:
        from core.advanced_features import list_recent_decisions
        decs = list_recent_decisions() or []
        out["shield"]["intercepted"] = len(decs)
        out["shield"]["p0_p1_alerts"] = sum(1 for d in decs
                                              if d.get("level", "") in ("P0", "P1"))
    except Exception:
        pass
    # mentor
    try:
        from core.mentor.knowledge_base import KB_STATS
        out["mentor"]["drafts"] = KB_STATS.get("draft_count", 0)
    except Exception:
        pass
    # pilot
    try:
        from core.agent_pilot.application import (
            default_pilot_learner,
            default_task_service,
        )
        svc = default_task_service()
        s = svc.stats()
        out["pilot"]["tasks_total"] = s.get("total", 0)
        out["pilot"]["tasks_delivered"] = s.get("delivered", 0)
        out["pilot"]["skills_auto"] = len(default_pilot_learner().list_skills())
    except Exception:
        pass
    return out


def _intent_stats() -> Dict[str, Any]:
    """主动识别命中统计：cooldown + ignore + 命中分布."""
    try:
        from bot.pilot_router import default_pilot_router
        r = default_pilot_router()
        cd = r.intent_detector.cooldown
        return {
            "fired_count": len(cd._fired),
            "ignored_count": len(cd._ignored),
            "cooldown_sec": cd.default_cooldown_sec,
            "rule_threshold": r.intent_detector.cfg.rule_threshold,
            "llm_min_confidence": r.intent_detector.cfg.llm_min_confidence,
        }
    except Exception as e:
        logger.debug("intent_stats failed: %s", e)
        return {"fired_count": 0, "ignored_count": 0, "cooldown_sec": 0,
                "rule_threshold": 0, "llm_min_confidence": 0}


def _memory_content(tenant: str = "default") -> Dict[str, Any]:
    out = {"tenant": tenant, "tiers": []}
    try:
        from core.flow_memory.flow_memory_md import MEMORY_DIR, TIER_ORDER
        for tier in TIER_ORDER:
            d = MEMORY_DIR / tier
            if not d.exists():
                continue
            files = []
            for f in sorted(d.glob("*.md")):
                content = ""
                try:
                    content = f.read_text(encoding="utf-8")
                except Exception:
                    pass
                files.append({"name": f.name, "size": f.stat().st_size,
                                "content": content[:1000]})
            if files:
                out["tiers"].append({"tier": tier, "files": files})
    except Exception as e:
        logger.debug("memory_content failed: %s", e)
    return out


# ── FastAPI Mounting ──────────────────────────────────────────────────────


def install_v7_routes(app, *, static_dir: Optional[Path] = None) -> None:
    """Mount v7 endpoints onto an existing FastAPI app.

    ``static_dir`` defaults to ``dashboard/static_v7``. The HTML files are
    auto-generated below if they don't exist (so this module is fully
    self-contained for tests).
    """
    from fastapi.responses import JSONResponse, HTMLResponse, FileResponse

    static_dir = static_dir or Path(__file__).parent / "static_v7"
    static_dir.mkdir(parents=True, exist_ok=True)
    _ensure_html(static_dir)

    @app.get("/api/v7/tasks")
    def _r_tasks(limit: int = 50):
        return JSONResponse(_list_tasks(limit=limit))

    @app.get("/api/v7/tasks/{task_id}")
    def _r_task_detail(task_id: str):
        d = _task_detail(task_id)
        if d is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse(d)

    @app.get("/api/v7/tasks/{task_id}/timeline")
    def _r_task_timeline(task_id: str):
        d = _task_detail(task_id)
        if d is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse({
            "transitions": d.get("transitions", []),
            "agent_logs": d.get("agent_logs", []),
        })

    @app.get("/api/v7/skills")
    def _r_skills():
        return JSONResponse(_list_skills())

    @app.get("/api/v7/triad")
    def _r_triad():
        return JSONResponse(_triad_data())

    @app.get("/api/v7/intent_stats")
    def _r_intent_stats():
        return JSONResponse(_intent_stats())

    @app.get("/api/v7/memory")
    def _r_memory(tenant: str = "default"):
        return JSONResponse(_memory_content(tenant))

    @app.get("/v7/pilot", response_class=HTMLResponse)
    def _r_pilot_page():
        return FileResponse(static_dir / "pilot_v7.html")

    @app.get("/v7/memory", response_class=HTMLResponse)
    def _r_memory_page():
        return FileResponse(static_dir / "memory_v7.html")

    @app.get("/v7/triad", response_class=HTMLResponse)
    def _r_triad_page():
        return FileResponse(static_dir / "triad_v7.html")


# ── 自带 3 个静态页 ──────────────────────────────────────────────────────


def _ensure_html(static_dir: Path) -> None:
    pilot_v7 = static_dir / "pilot_v7.html"
    memory_v7 = static_dir / "memory_v7.html"
    triad_v7 = static_dir / "triad_v7.html"

    if not pilot_v7.exists():
        pilot_v7.write_text(_PILOT_HTML, encoding="utf-8")
    if not memory_v7.exists():
        memory_v7.write_text(_MEMORY_HTML, encoding="utf-8")
    if not triad_v7.exists():
        triad_v7.write_text(_TRIAD_HTML, encoding="utf-8")


_PILOT_HTML = """<!doctype html>
<html lang=zh>
<head>
<meta charset=utf-8>
<title>Agent-Pilot · 主驾驶舱</title>
<style>
body { font-family: -apple-system, "PingFang SC", sans-serif; margin: 0; padding: 24px; background: #f7f8fa; }
h1 { margin-top: 0; }
.subtitle { color: #888; margin-bottom: 24px; }
.row { display: grid; grid-template-columns: 1fr 2fr; gap: 24px; }
.panel { background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.task { padding: 8px; border-bottom: 1px solid #eee; cursor: pointer; }
.task:hover { background: #f0f2f5; }
.state { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.state-suggested { background: #ffd; color: #774; }
.state-assigned { background: #def; color: #258; }
.state-planning { background: #def0ff; color: #057; }
.state-doc_generating, .state-ppt_generating, .state-canvas_generating { background: #ffeaa7; color: #6c5300; }
.state-reviewing { background: #fff3cd; color: #856404; }
.state-delivered { background: #d4edda; color: #155724; }
.state-paused { background: #e9ecef; color: #495057; }
.state-failed { background: #f8d7da; color: #721c24; }
.state-ignored { background: #eee; color: #999; }
.log { font-size: 12px; padding: 4px 0; border-bottom: 1px dotted #eee; }
.log-agent { font-weight: bold; color: #258; }
.log-thought { color: #555; }
.log-result { color: #185; }
.log-error { color: #c33; }
nav a { margin-right: 12px; color: #258; text-decoration: none; }
</style>
</head>
<body>
<nav><a href="/v7/pilot">Pilot 主驾驶舱</a><a href="/v7/memory">6 级 Memory 时间线</a><a href="/v7/triad">三线雷达</a></nav>
<h1>Agent-Pilot · 主驾驶舱</h1>
<div class=subtitle>PRD §8 · 任务列表 + 详情 + Agent 日志 + 成果资产</div>
<div class=row>
  <div class=panel>
    <h3>任务列表</h3>
    <div id=tasks>加载中…</div>
  </div>
  <div class=panel>
    <h3>任务详情</h3>
    <div id=detail>选择左侧任务查看 Agent 日志</div>
  </div>
</div>
<script>
async function loadTasks() {
  const r = await fetch('/api/v7/tasks');
  const list = await r.json();
  const html = list.map(t =>
    `<div class=task onclick="showDetail('${t.task_id}')">
       <span class="state state-${t.state}">${t.state}</span>
       <strong>${t.title || '(无标题)'}</strong>
       <small style="color:#999">· ${t.task_id.slice(-8)}</small>
       <div style="color:#999;font-size:11px">${t.intent}</div>
     </div>`
  ).join('');
  document.getElementById('tasks').innerHTML = html || '<em>暂无任务</em>';
}
async function showDetail(id) {
  const r = await fetch('/api/v7/tasks/' + id);
  if (!r.ok) { document.getElementById('detail').innerHTML = '<em>未找到</em>'; return; }
  const t = await r.json();
  const trans = (t.transitions || []).map(tr =>
    `<div class=log><span class=log-agent>[${tr.event}]</span> ${tr.from_state} → ${tr.to_state}
        <small style=color:#999>· actor=${tr.actor_open_id || 'system'}</small></div>`
  ).join('');
  const logs = (t.agent_logs || []).map(l =>
    `<div class="log log-${l.kind}"><span class=log-agent>${l.agent}</span> [${l.kind}] ${l.content}</div>`
  ).join('');
  document.getElementById('detail').innerHTML = `
    <h4>${t.title}</h4>
    <p>${t.intent}</p>
    <div><strong>Owner:</strong> ${(t.owner_lock||{}).owner_open_id || '-'}</div>
    <div><strong>State:</strong> <span class="state state-${t.state}">${t.state}</span></div>
    <h5>状态转移历史</h5>${trans || '<em>无</em>'}
    <h5>Agent 日志</h5>${logs || '<em>无</em>'}
    <h5>产出物</h5>${(t.artifacts||[]).map(a => `<div>📄 ${a.title} <a href='${a.feishu_url || a.local_path}'>打开</a></div>`).join('') || '<em>无</em>'}
  `;
}
loadTasks();
setInterval(loadTasks, 5000);
</script>
</body>
</html>
"""

_MEMORY_HTML = """<!doctype html>
<html lang=zh>
<head>
<meta charset=utf-8>
<title>6 级 Memory 时间线</title>
<style>
body { font-family: -apple-system, "PingFang SC", sans-serif; margin: 0; padding: 24px; background: #f7f8fa; }
.tier { background: white; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.tier h3 { margin-top: 0; color: #258; }
.tier .file { padding: 8px; border-bottom: 1px dotted #eee; font-family: monospace; font-size: 12px; white-space: pre-wrap; }
nav a { margin-right: 12px; color: #258; text-decoration: none; }
</style>
</head>
<body>
<nav><a href="/v7/pilot">Pilot 主驾驶舱</a><a href="/v7/memory">6 级 Memory 时间线</a><a href="/v7/triad">三线雷达</a></nav>
<h1>6 级 Memory 时间线</h1>
<p>低层覆盖高层：Enterprise → Workspace → Department → Group → User → Session</p>
<div id=root>加载中…</div>
<script>
async function load() {
  const r = await fetch('/api/v7/memory?tenant=default');
  const data = await r.json();
  if (!data.tiers || !data.tiers.length) {
    document.getElementById('root').innerHTML =
      '<em>暂无 markdown 内容（在 data/flow_memory_md/&lt;tier&gt;/&lt;id&gt;.md 创建）</em>';
    return;
  }
  document.getElementById('root').innerHTML = data.tiers.map(t =>
    `<div class=tier>
       <h3>${t.tier}</h3>
       ${t.files.map(f =>
         `<div class=file><strong>${f.name}</strong> · ${f.size} bytes\\n${f.content}</div>`
       ).join('')}
     </div>`
  ).join('');
}
load();
</script>
</body>
</html>
"""

_TRIAD_HTML = """<!doctype html>
<html lang=zh>
<head>
<meta charset=utf-8>
<title>三线协同雷达</title>
<style>
body { font-family: -apple-system, "PingFang SC", sans-serif; margin: 0; padding: 24px; background: #f7f8fa; }
.line { background: white; border-radius: 8px; padding: 24px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.line h2 { margin-top: 0; }
.metric { display: inline-block; padding: 8px 16px; margin: 4px; background: #f0f4ff; border-radius: 6px; }
.shield { border-left: 4px solid #c33; }
.mentor { border-left: 4px solid #258; }
.pilot { border-left: 4px solid #185; }
nav a { margin-right: 12px; color: #258; text-decoration: none; }
</style>
</head>
<body>
<nav><a href="/v7/pilot">Pilot 主驾驶舱</a><a href="/v7/memory">6 级 Memory 时间线</a><a href="/v7/triad">三线雷达</a></nav>
<h1>三线协同雷达</h1>
<p>「工位上同时发生」立意工程兑现：左线 @shield + 右线 @mentor + 主线 @pilot 共享 KB / Recovery Card / FlowMemory</p>
<div id=root>加载中…</div>
<script>
async function load() {
  const r = await fetch('/api/v7/triad');
  const d = await r.json();
  document.getElementById('root').innerHTML = `
    <div class="line shield">
      <h2>🛡️ 左线 · @shield · 消息守护</h2>
      <div class=metric>已拦截 <strong>${d.shield.intercepted}</strong> 条</div>
      <div class=metric>P0/P1 紧急 <strong>${d.shield.p0_p1_alerts}</strong></div>
    </div>
    <div class="line mentor">
      <h2>✍️ 右线 · @mentor · 表达带教</h2>
      <div class=metric>草稿 <strong>${d.mentor.drafts}</strong></div>
    </div>
    <div class="line pilot">
      <h2>🛫 主线 · @pilot · 主驾驶</h2>
      <div class=metric>任务总数 <strong>${d.pilot.tasks_total}</strong></div>
      <div class=metric>已交付 <strong>${d.pilot.tasks_delivered}</strong></div>
      <div class=metric>自动 SKILL <strong>${d.pilot.skills_auto}</strong></div>
    </div>
  `;
}
load();
setInterval(load, 5000);
</script>
</body>
</html>
"""


__all__ = [
    "install_v7_routes",
]

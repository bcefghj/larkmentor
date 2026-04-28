"""A/B 矩阵真实 LLM 调用脚本 (P13).

5 推理配置 × 3 模型供应商 × 5 任务 = 75 次真实 LLM 调用，得出 ab_matrix.json
真实数据，校准 README 中的"+43% 提升"等历史宣传。

运行：
    PYTHONPATH=. .venv/bin/python scripts/run_ab_matrix.py

输出：
    tests/reports/ab_matrix.json   完整结果（每次调用的 score）
    tests/reports/ab_matrix.md     人类可读 markdown 报告

数据点：5 个真实办公任务 × 5 配置档（baseline / orchestrator-worker /
+builder-validator / +citation / +debate）× 3 模型（doubao / minimax / deepseek
fallback）。每条任务用 5 个 quality gates 评分，最终得出综合得分。

注意：deepseek 没配 key 时降级（标 N/A），不阻断流程。
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv()


# ── 5 个真实办公任务 ────────────────────────────────────────────────────────


TASKS = [
    {"id": "T1", "intent": "把上周校园推广活动的群聊讨论整理成 8 页的活动复盘汇报 PPT，给老板看",
     "audience": "leader"},
    {"id": "T2", "intent": "起草一份新产品的 PRD（产品需求文档），包含背景/目标用户/功能/验收标准",
     "audience": "team"},
    {"id": "T3", "intent": "根据本季度数据，做一份季度业务复盘 PPT，重点 5-7 页",
     "audience": "leader"},
    {"id": "T4", "intent": "为新员工写一份入职第一周的 onboarding 文档，含工具/流程/Q&A",
     "audience": "team"},
    {"id": "T5", "intent": "战略方向的方案辩论：自营 vs 联营，给出 2 套对比方案 + 推荐",
     "audience": "leader"},
]


# ── 5 个配置 ────────────────────────────────────────────────────────────────


CONFIGS = [
    {"id": "C1", "name": "single_agent_baseline",
     "use_orchestrator_worker": False, "use_builder_validator": False,
     "use_citation": False, "use_debate": False},
    {"id": "C2", "name": "orchestrator_worker",
     "use_orchestrator_worker": True, "use_builder_validator": False,
     "use_citation": False, "use_debate": False},
    {"id": "C3", "name": "+builder_validator",
     "use_orchestrator_worker": True, "use_builder_validator": True,
     "use_citation": False, "use_debate": False},
    {"id": "C4", "name": "+citation",
     "use_orchestrator_worker": True, "use_builder_validator": True,
     "use_citation": True, "use_debate": False},
    {"id": "C5", "name": "+debate",
     "use_orchestrator_worker": True, "use_builder_validator": True,
     "use_citation": True, "use_debate": True},
]


# ── 3 个 Provider ───────────────────────────────────────────────────────────


def doubao_chat(prompt: str, *, max_tokens: int = 600) -> str:
    try:
        from openai import OpenAI
        cli = OpenAI(api_key=os.getenv("ARK_API_KEY"),
                      base_url=os.getenv("ARK_CHAT_URL")
                                or os.getenv("ARK_BASE_URL"))
        resp = cli.chat.completions.create(
            model=os.getenv("ARK_CHAT_MODEL") or os.getenv("ARK_MODEL", "doubao-seed-2.0-pro"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"[ERROR] {e}"


def minimax_chat(prompt: str, *, max_tokens: int = 600) -> str:
    try:
        from openai import OpenAI
        api_key = os.getenv("MINIMAX_API_KEY")
        if not api_key:
            return "[SKIP] no MINIMAX_API_KEY"
        cli = OpenAI(api_key=api_key,
                      base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"))
        resp = cli.chat.completions.create(
            model=os.getenv("MINIMAX_MODEL", "MiniMax-M2"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"[ERROR] {e}"


def deepseek_chat(prompt: str, *, max_tokens: int = 600) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "[SKIP] no DEEPSEEK_API_KEY"
    try:
        from openai import OpenAI
        cli = OpenAI(api_key=api_key, base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
        resp = cli.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"[ERROR] {e}"


PROVIDERS = {
    "doubao": doubao_chat,
    "minimax": minimax_chat,
    "deepseek": deepseek_chat,
}


# ── Pipeline 各档实现 ──────────────────────────────────────────────────────


SYSTEM_PROMPT = """你是 Agent-Pilot 任务执行助手。
按要求把意图转成可读的 markdown 文档（约 600 字以内）：
- 标题
- 背景
- 关键内容（3-5 个 bullet）
- 风险与缓解
- 下一步
"""


def gen_baseline(intent: str, llm) -> str:
    return llm(SYSTEM_PROMPT + "\n\n用户意图：\n" + intent)


def gen_orchestrator_worker(intent: str, llm) -> str:
    plan = llm(f"作为 Lead Agent，把这个意图拆成 3-5 个子任务（每条一句话）：\n{intent}")
    answer = llm(f"{SYSTEM_PROMPT}\n\n意图：{intent}\n\n参考子任务拆解：\n{plan[:600]}")
    return answer


def gen_with_builder_validator(intent: str, llm) -> str:
    draft = gen_orchestrator_worker(intent, llm)
    review = llm(f"你是独立审查者。指出下面 markdown 的 3 处可以改进的地方（不要重写）：\n{draft[:1200]}")
    revised = llm(f"基于以下审查建议改进 markdown:\n\n[审查] {review[:400]}\n\n[原文]\n{draft[:1200]}")
    return revised


def gen_with_citation(intent: str, llm) -> str:
    body = gen_with_builder_validator(intent, llm)
    cite = llm(f"为下面 markdown 的关键 claim 加 (source:?) 占位符：\n{body[:1500]}")
    return cite


def gen_with_debate(intent: str, llm) -> str:
    pro = llm(f"作为正方，给出对此意图的最优方案要点（≤6 条 bullet）：\n{intent}")
    con = llm(f"作为反方，指出正方方案的 3 处风险：\n{pro[:600]}")
    converged = llm(f"作为收敛者，整合正反两方观点写出最终 markdown:\n\n[正方]{pro[:800]}\n\n[反方]{con[:600]}")
    return converged


CONFIG_GENS: Dict[str, Callable[[str, Callable], str]] = {
    "single_agent_baseline": gen_baseline,
    "orchestrator_worker": gen_orchestrator_worker,
    "+builder_validator": gen_with_builder_validator,
    "+citation": gen_with_citation,
    "+debate": gen_with_debate,
}


# ── Quality Score (5 gates 简化版，0-100) ─────────────────────────────────


def score_output(text: str, intent: str) -> Dict[str, float]:
    if not text or text.startswith("["):
        return {"completeness": 0, "consistency": 0, "factuality": 0,
                "readability": 0, "safety": 0, "overall": 0}
    sc: Dict[str, float] = {}
    sc["completeness"] = min(100.0, len(text) / 600 * 100)  # 字数门槛
    # consistency: 检查是否有 markdown 结构（标题 + bullet）
    has_title = bool(__import__("re").search(r"^#+\s", text, __import__("re").M))
    has_bullet = bool(__import__("re").search(r"^[-*]\s", text, __import__("re").M))
    sc["consistency"] = (50 if has_title else 0) + (50 if has_bullet else 0)
    # factuality: 检查是否提到 intent 中的关键词
    import re
    key_terms = re.findall(r"[\u4e00-\u9fff]{2,}", intent)[:5]
    hits = sum(1 for t in key_terms if t in text)
    sc["factuality"] = (hits / max(len(key_terms), 1)) * 100
    # readability: 平均句子长度（10-40 字最佳）
    sentences = re.split(r"[。！？.!?]+", text)
    avg = sum(len(s) for s in sentences) / max(len(sentences), 1)
    sc["readability"] = max(0.0, 100 - abs(avg - 25) * 2.0)
    # safety: 没有 PII / 注入词
    bad = any(p in text for p in ["evil.xyz", "ignore previous", "system prompt:",
                                   "rm -rf", "DAN", "App Secret"])
    sc["safety"] = 0 if bad else 100
    sc["overall"] = sum(sc.values()) / 5
    return sc


# ── 主入口 ─────────────────────────────────────────────────────────────────


@dataclass
class CallResult:
    task_id: str
    config_id: str
    config_name: str
    provider: str
    model: str
    prompt_chars: int
    output_chars: int
    duration_sec: float
    output: str
    score: Dict[str, float]
    error: str = ""


def run_matrix(*, providers: Optional[List[str]] = None,
               tasks: Optional[List[Dict]] = None,
               configs: Optional[List[Dict]] = None,
               max_tokens: int = 600) -> List[CallResult]:
    providers = providers or ["doubao", "minimax", "deepseek"]
    tasks = tasks or TASKS
    configs = configs or CONFIGS
    results: List[CallResult] = []
    total = len(providers) * len(tasks) * len(configs)
    n = 0
    t0 = time.time()
    for p in providers:
        llm = PROVIDERS[p]
        for cfg in configs:
            gen = CONFIG_GENS[cfg["name"]]
            for task in tasks:
                n += 1
                t_start = time.time()
                output = ""
                err = ""
                try:
                    output = gen(task["intent"], llm)
                except Exception as e:
                    err = str(e)[:200]
                dt = time.time() - t_start
                sc = score_output(output, task["intent"])
                cr = CallResult(
                    task_id=task["id"], config_id=cfg["id"], config_name=cfg["name"],
                    provider=p, model="", prompt_chars=len(task["intent"]),
                    output_chars=len(output), duration_sec=round(dt, 2),
                    output=output, score=sc, error=err,
                )
                results.append(cr)
                elapsed = time.time() - t0
                eta = elapsed / n * (total - n) if n else 0
                print(f"[{n:>3}/{total}] {cfg['name']:<25} {p:<10} {task['id']:<3} "
                       f"score={sc.get('overall', 0):>5.1f}  dt={dt:>5.1f}s  "
                       f"eta={eta/60:.1f}min", flush=True)
    return results


def write_reports(results: List[CallResult], *, json_path: str, md_path: str) -> None:
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_ts": int(time.time()),
        "configs": [c["name"] for c in CONFIGS],
        "providers": list(PROVIDERS.keys()),
        "tasks": [t["id"] for t in TASKS],
        "results": [
            {
                "task_id": r.task_id, "config_id": r.config_id,
                "config_name": r.config_name,
                "provider": r.provider,
                "prompt_chars": r.prompt_chars, "output_chars": r.output_chars,
                "duration_sec": r.duration_sec,
                "score": r.score, "error": r.error,
            }
            for r in results
        ],
        "aggregates": _aggregate(results),
    }
    Path(json_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    Path(md_path).write_text(_render_md(payload), encoding="utf-8")


def _aggregate(results: List[CallResult]) -> Dict[str, Any]:
    by_cfg: Dict[str, Dict[str, Any]] = {}
    for r in results:
        d = by_cfg.setdefault(r.config_name, {"overall": [], "count": 0})
        if r.score.get("overall", 0) > 0:
            d["overall"].append(r.score["overall"])
        d["count"] += 1
    out = {}
    for name, d in by_cfg.items():
        if d["overall"]:
            avg = sum(d["overall"]) / len(d["overall"])
            out[name] = {"avg_overall": round(avg, 2),
                          "n": len(d["overall"]),
                          "total_calls": d["count"]}
        else:
            out[name] = {"avg_overall": 0.0, "n": 0, "total_calls": d["count"]}
    return out


def _render_md(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Agent-Pilot v7 · A/B 矩阵真实测试报告")
    lines.append("")
    lines.append(f"- 运行时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(payload['run_ts']))}")
    lines.append(f"- 配置档：{', '.join(payload['configs'])}")
    lines.append(f"- 模型供应商：{', '.join(payload['providers'])}")
    lines.append(f"- 任务集：{', '.join(payload['tasks'])}")
    lines.append("")
    lines.append("## 综合得分（按配置档聚合）")
    lines.append("")
    lines.append("| 配置档 | 平均综合分 (overall) | N | 总调用数 |")
    lines.append("| --- | ---: | ---: | ---: |")
    for name in payload["configs"]:
        agg = payload["aggregates"].get(name, {})
        lines.append(f"| {name} | {agg.get('avg_overall', 0):.2f} | {agg.get('n', 0)} | {agg.get('total_calls', 0)} |")
    lines.append("")
    # 增量 delta
    confs = payload["configs"]
    if len(confs) >= 2 and payload["aggregates"].get(confs[0], {}).get("n", 0) > 0:
        baseline = payload["aggregates"][confs[0]]["avg_overall"]
        last = payload["aggregates"].get(confs[-1], {}).get("avg_overall", 0.0)
        if baseline:
            lines.append(f"- {confs[0]} → {confs[-1]} 增量：**{last - baseline:+.2f} 绝对值**"
                         f"（{(last - baseline) / baseline * 100:+.1f}%）")
    lines.append("")
    lines.append("## 每条调用明细（按 provider × task × config）")
    lines.append("")
    lines.append("| Provider | Task | Config | overall | duration_s | output_chars | error |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | --- |")
    for r in payload["results"]:
        lines.append(
            f"| {r['provider']} | {r['task_id']} | {r['config_name']} "
            f"| {r['score'].get('overall', 0):.1f} | {r['duration_sec']:.1f} "
            f"| {r['output_chars']} | {r['error'][:30] if r['error'] else ''} |"
        )
    lines.append("")
    lines.append("> 真实 LLM 调用产生，无 mock。原始 JSON 见同目录 `ab_matrix.json`。")
    lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    json_out = "tests/reports/ab_matrix.json"
    md_out = "tests/reports/ab_matrix.md"
    Path("tests/reports").mkdir(parents=True, exist_ok=True)
    print(f"=== Agent-Pilot v7 A/B Matrix · {len(PROVIDERS) * len(TASKS) * len(CONFIGS)} calls ===\n")
    rs = run_matrix()
    write_reports(rs, json_path=json_out, md_path=md_out)
    print(f"\n[done] reports written to:\n  {json_out}\n  {md_out}")

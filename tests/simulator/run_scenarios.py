"""Scenario test runner.

Loads all YAML scenarios, runs them through the deterministic 6-dim
classifier (no LLM, no Feishu API), compares to expected_level, and
emits an HTML accuracy report.

Usage:
    python tests/simulator/run_scenarios.py [--category xxx] [--no-html]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.simulator.scenario_loader import load_all_scenarios, filter_scenarios  # noqa
from core.classification_engine import classify  # noqa
from core.sender_profile import (  # noqa
    SenderProfile, IDENTITY_VIP, IDENTITY_SUPERIOR, IDENTITY_PEER,
    IDENTITY_OCCASIONAL, IDENTITY_UNKNOWN, IDENTITY_BOT,
)
from memory.user_state import UserState  # noqa


REPORT_DIR = ROOT / "tests" / "reports"


IDENTITY_MAP = {
    "vip": IDENTITY_VIP, "superior": IDENTITY_SUPERIOR,
    "peer": IDENTITY_PEER, "occasional": IDENTITY_OCCASIONAL,
    "unknown": IDENTITY_UNKNOWN, "bot": IDENTITY_BOT,
}


def _make_user(scenario) -> UserState:
    u = UserState(open_id=f"test_user_{scenario['id']}")
    u.work_context = scenario.get("user_context", "")
    u.whitelist = scenario.get("user_whitelist", []) or []
    return u


def _make_profile(scenario) -> SenderProfile:
    s = scenario.get("sender", {})
    p = SenderProfile(
        sender_id=s.get("id", ""),
        name=s.get("name", ""),
        identity_tag=IDENTITY_MAP.get(s.get("identity", "peer"), IDENTITY_PEER),
        recent_messages_count=s.get("recent_messages_count", 5),
        total_messages_count=s.get("total_messages_count", 10),
    )
    return p


def run_one(scenario):
    u = _make_user(scenario)
    p = _make_profile(scenario)
    chat = scenario.get("chat", {})
    res = classify(
        user=u,
        sender_profile=p,
        message_text=scenario.get("message", ""),
        chat_type=chat.get("type", "group"),
        chat_name=chat.get("name", ""),
        member_count=chat.get("member_count"),
    )
    return res


def run_all(category=None):
    scenarios = load_all_scenarios()
    if category:
        scenarios = filter_scenarios(scenarios, category)
    results = []
    t0 = time.time()
    for sc in scenarios:
        res = run_one(sc)
        passed = res.level == sc.get("expected_level")
        results.append({
            "scenario": sc, "result": res, "passed": passed,
        })
    elapsed = time.time() - t0
    return results, elapsed


def summarize(results):
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    by_cat = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        cat = r["scenario"].get("category", "uncategorized")
        by_cat[cat]["total"] += 1
        if r["passed"]:
            by_cat[cat]["passed"] += 1
    return {
        "total": total, "passed": passed,
        "accuracy": passed / total if total else 0.0,
        "by_category": dict(by_cat),
    }


def render_html(results, summary, elapsed_sec) -> str:
    rows = []
    for r in results:
        sc = r["scenario"]; res = r["result"]
        chat = sc.get("chat", {})
        sender = sc.get("sender", {})
        status = "PASS" if r["passed"] else "FAIL"
        status_cls = "pass" if r["passed"] else "fail"
        dim_str = " ".join(
            f'<span class="dim">{k}:{v:.2f}</span>'
            for k, v in (res.dimensions or {}).items()
        )
        rows.append(f"""
        <tr class="{status_cls}">
          <td><span class="status">{status}</span></td>
          <td>{sc['id']}</td>
          <td>{sc.get('category','')}</td>
          <td>{sc.get('description','')}</td>
          <td>{sender.get('name','')} ({sender.get('identity','')})</td>
          <td>{chat.get('type','')} {chat.get('name','')}</td>
          <td class="msg">{(sc.get('message','') or '<i>(empty)</i>')[:80]}</td>
          <td>{sc.get('expected_level','')}</td>
          <td><strong>{res.level}</strong> ({res.score:.2f})</td>
          <td class="dims">{dim_str}</td>
        </tr>""")
    rows_html = "\n".join(rows)

    cat_rows = "\n".join(
        f"<tr><td>{c}</td><td>{v['passed']}/{v['total']}</td>"
        f"<td>{(v['passed']/v['total']*100):.1f}%</td></tr>"
        for c, v in summary["by_category"].items()
    )

    accuracy_pct = summary["accuracy"] * 100
    color = "#10B981" if accuracy_pct >= 90 else ("#F59E0B" if accuracy_pct >= 75 else "#EF4444")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>LarkMentor 分类引擎准确率报告</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #F8FAFC; color: #0F172A; margin: 0; padding: 32px; }}
  .container {{ max-width: 1280px; margin: 0 auto; }}
  h1 {{ margin: 0 0 4px 0; font-weight: 700; font-size: 28px; }}
  .meta {{ color: #64748B; margin-bottom: 24px; }}
  .summary {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
  .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
  .card .label {{ font-size: 12px; color: #64748B; text-transform: uppercase; letter-spacing: 0.05em; }}
  .card .value {{ font-size: 32px; font-weight: 700; margin-top: 4px; }}
  .accuracy .value {{ color: {color}; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden;
           box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
  th {{ text-align: left; padding: 12px 16px; background: #F1F5F9; font-size: 12px;
        text-transform: uppercase; color: #475569; border-bottom: 1px solid #E2E8F0; }}
  td {{ padding: 12px 16px; font-size: 13px; border-bottom: 1px solid #F1F5F9; vertical-align: top; }}
  tr.fail td {{ background: #FEF2F2; }}
  .status {{ font-weight: 600; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
  tr.pass .status {{ background: #DCFCE7; color: #166534; }}
  tr.fail .status {{ background: #FEE2E2; color: #991B1B; }}
  .dims .dim {{ display: inline-block; background: #EEF2FF; color: #3730A3; padding: 1px 6px;
                border-radius: 3px; margin-right: 4px; margin-top: 2px; font-size: 11px; }}
  .msg {{ max-width: 280px; }}
  h2 {{ margin-top: 32px; }}
</style></head><body><div class="container">
<h1>LarkMentor 6 维分类引擎准确率报告</h1>
<div class="meta">运行 {summary['total']} 个场景 · 耗时 {elapsed_sec:.2f}s · 报告时间 {time.strftime('%Y-%m-%d %H:%M:%S')}</div>

<div class="summary">
  <div class="card"><div class="label">总场景</div><div class="value">{summary['total']}</div></div>
  <div class="card"><div class="label">通过</div><div class="value">{summary['passed']}</div></div>
  <div class="card accuracy"><div class="label">总准确率</div><div class="value">{accuracy_pct:.1f}%</div></div>
</div>

<h2>分类别准确率</h2>
<table>
  <thead><tr><th>分类</th><th>通过/总数</th><th>准确率</th></tr></thead>
  <tbody>{cat_rows}</tbody>
</table>

<h2>详细结果</h2>
<table>
  <thead><tr>
    <th>状态</th><th>ID</th><th>分类</th><th>描述</th>
    <th>发送者</th><th>频道</th><th>消息</th>
    <th>期望</th><th>实际</th><th>6 维分数</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>

</div></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category")
    ap.add_argument("--no-html", action="store_true")
    args = ap.parse_args()

    print(f"Loading scenarios{' for ' + args.category if args.category else ''}...")
    results, elapsed = run_all(args.category)
    summary = summarize(results)

    print(f"\n{'='*70}")
    print(f"LarkMentor Classification Engine - Test Report")
    print(f"{'='*70}")
    print(f"Scenarios: {summary['total']}")
    print(f"Passed:    {summary['passed']}")
    print(f"Accuracy:  {summary['accuracy']*100:.1f}%")
    print(f"Time:      {elapsed:.2f}s")
    print(f"\nBy category:")
    for cat, v in summary["by_category"].items():
        pct = v['passed'] / v['total'] * 100 if v['total'] else 0
        print(f"  {cat:20s} {v['passed']}/{v['total']:3d}  ({pct:.1f}%)")

    failed = [r for r in results if not r["passed"]]
    if failed:
        print(f"\nFailures ({len(failed)}):")
        limit = 100 if os.environ.get("VERBOSE") else 10
        for r in failed[:limit]:
            sc = r["scenario"]; res = r["result"]
            print(f"  {sc['id']:20s} expected={sc.get('expected_level')} got={res.level} "
                  f"({res.score:.2f}) | {sc.get('description','')[:50]}")
        if len(failed) > limit:
            print(f"  ... and {len(failed)-limit} more")

    if not args.no_html:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORT_DIR / "classification_accuracy.html"
        out.write_text(render_html(results, summary, elapsed), encoding="utf-8")
        print(f"\nHTML report: {out}")

    sys.exit(0 if summary['accuracy'] >= 0.75 else 1)


if __name__ == "__main__":
    main()

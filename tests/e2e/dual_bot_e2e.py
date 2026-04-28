"""Dual-Bot End-to-End Test Driver.

This script uses the *TestSender* Feishu app to send a series of messages
to a target user (the developer's Feishu account). The *LarkMentor* main
bot (the system under test) processes them and sends back classifications,
auto-replies, and cards.

Setup:
    Set environment variables before running:
        TEST_SENDER_APP_ID    – TestSender Bot App ID
        TEST_SENDER_APP_SECRET – TestSender Bot App Secret
        TEST_TARGET_OPEN_ID   – the developer's open_id receiving messages
        TEST_TARGET_CHAT_ID   – (optional) group chat both bots are in
        TEST_PAUSE_SEC        – pause between messages (default 8)

Usage:
    python tests/e2e/dual_bot_e2e.py [--scenario short|standard|stress]

Scenarios:
    short    : 5 representative messages
    standard : 15 messages covering all priority levels
    stress   : 30 messages including a circuit-breaker burst at the end
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import lark_oapi as lark


SHORT_SCRIPT = [
    ("hello", "你好 LarkMentor，先做个自我介绍吧"),
    ("urgent", "线上紧急故障！订单服务挂了，立即处理"),
    ("question", "请教一下 FastAPI 怎么实现 streaming"),
    ("chitchat", "今天午饭吃啥呀"),
    ("context", "我现在在做 Q3 产品方案，重点是用户增长模型"),
]


STANDARD_SCRIPT = [
    ("greet", "你好"),
    ("focus_start", "开始专注 30 分钟"),
    ("urgent_p0", "P0 紧急故障，需要立刻处理"),
    ("decision_p0", "请尽快批准这份合同"),
    ("question_p1", "MR !1234 麻烦帮 review 一下"),
    ("time_p0", "30 分钟内能给我答复吗，立刻要结论"),
    ("chitchat_p3", "哈哈这表情包笑死我了"),
    ("broadcast_p3", "本周市场周报已发布"),
    ("relevant_p1", "Q3 用户增长方案我有些建议想和你讨论"),
    ("ask_status", "状态"),
    ("rookie_review", "帮我看看：这个需求怎么没说清楚啊"),
    ("workspace", "演示工作台"),
    ("recent_decisions", "最近决策"),
    ("end_focus", "结束专注"),
    ("daily_report", "今日报告"),
]


STRESS_SCRIPT = STANDARD_SCRIPT + [
    (f"burst_p0_{i}", f"紧急！服务故障 #{i}") for i in range(5)
] + [
    ("post_burst_status", "状态"),
    ("post_burst_audit", "最近决策"),
    ("rollback_test", "回滚 abc_def01 P3"),
]


def _build_test_client():
    app_id = os.environ.get("TEST_SENDER_APP_ID", "")
    app_secret = os.environ.get("TEST_SENDER_APP_SECRET", "")
    if not (app_id and app_secret):
        raise RuntimeError("Set TEST_SENDER_APP_ID and TEST_SENDER_APP_SECRET")
    return lark.Client.builder().app_id(app_id).app_secret(app_secret).build()


def _send_text(client, target_user_id: str, text: str, chat_id: str = None) -> bool:
    import json as _json
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest, CreateMessageRequestBody,
    )
    if chat_id:
        receive_id = chat_id
        receive_id_type = "chat_id"
    else:
        receive_id = target_user_id
        receive_id_type = "open_id"
    req = (
        CreateMessageRequest.builder()
        .receive_id_type(receive_id_type)
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type("text")
            .content(_json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        .build()
    )
    resp = client.im.v1.message.create(req)
    return resp.success()


def run(scenario_name: str = "standard", pause_sec: int = None):
    target = os.environ.get("TEST_TARGET_OPEN_ID")
    chat_id = os.environ.get("TEST_TARGET_CHAT_ID")
    if not (target or chat_id):
        print("ERROR: Set TEST_TARGET_OPEN_ID (private chat) or TEST_TARGET_CHAT_ID (group chat)")
        sys.exit(1)
    pause = pause_sec or int(os.environ.get("TEST_PAUSE_SEC", "8"))

    scripts = {"short": SHORT_SCRIPT, "standard": STANDARD_SCRIPT, "stress": STRESS_SCRIPT}
    script = scripts.get(scenario_name)
    if not script:
        print(f"Unknown scenario: {scenario_name}. Use one of: short/standard/stress")
        sys.exit(1)

    client = _build_test_client()
    print(f"Running '{scenario_name}' scenario with {len(script)} messages, "
          f"pause={pause}s, target={'chat:'+chat_id if chat_id else 'user:'+target[-8:]}")
    print("-" * 70)

    success = 0
    for tag, text in script:
        ok = _send_text(client, target, text, chat_id)
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {tag:20s} → {text[:50]}")
        if ok:
            success += 1
        time.sleep(pause)

    print("-" * 70)
    print(f"Sent {success}/{len(script)} messages successfully.")
    print(f"Now check the LarkMentor target account for cards/auto-replies.")
    sys.exit(0 if success == len(script) else 1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="standard",
                    choices=["short", "standard", "stress"])
    ap.add_argument("--pause", type=int, help="Pause seconds between messages")
    args = ap.parse_args()
    run(args.scenario, args.pause)

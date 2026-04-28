"""Tests for Smart Shield message classification."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.user_state import get_user, PendingMessage
from core.smart_shield import _contains_urgent_keyword, classify_message
from core.flow_detector import parse_command


class TestUrgentKeyword(unittest.TestCase):
    def test_chinese_urgent(self):
        self.assertTrue(_contains_urgent_keyword("这个事情很紧急"))

    def test_english_urgent(self):
        self.assertTrue(_contains_urgent_keyword("this is urgent"))

    def test_asap(self):
        self.assertTrue(_contains_urgent_keyword("Please reply ASAP"))

    def test_not_urgent(self):
        self.assertFalse(_contains_urgent_keyword("今天午饭吃什么"))

    def test_blocking(self):
        self.assertTrue(_contains_urgent_keyword("This is blocking production"))


class TestWhitelistClassification(unittest.TestCase):
    def test_whitelist_sender_gets_p0(self):
        user = get_user("test_wl_user")
        user.whitelist = ["张三"]
        result = classify_message(user, "张三", "uid_zhangsan", "普通消息", "技术群")
        self.assertEqual(result["level"], "P0")
        self.assertIn("白名单", result["reason"])

    def test_urgent_keyword_gets_p0(self):
        user = get_user("test_kw_user")
        result = classify_message(user, "李四", "uid_lisi", "线上紧急故障！", "运维群")
        self.assertEqual(result["level"], "P0")
        self.assertIn("紧急", result["reason"])


class TestCommandParsing(unittest.TestCase):
    def test_focus_commands(self):
        self.assertEqual(parse_command("开始专注")["command"], "start_focus")
        self.assertEqual(parse_command("focus")["command"], "start_focus")
        self.assertEqual(parse_command("专注")["command"], "start_focus")

    def test_timed_focus(self):
        r = parse_command("专注30分钟")
        self.assertEqual(r["command"], "start_focus")
        self.assertEqual(r["args"]["duration"], 30)

    def test_timed_focus_english(self):
        r = parse_command("focus 45")
        self.assertEqual(r["command"], "start_focus")
        self.assertEqual(r["args"]["duration"], 45)

    def test_end_focus(self):
        self.assertEqual(parse_command("结束专注")["command"], "end_focus")
        self.assertEqual(parse_command("done")["command"], "end_focus")

    def test_whitelist(self):
        r = parse_command("白名单 张三")
        self.assertEqual(r["command"], "set_whitelist")
        self.assertEqual(r["args"]["name"], "张三")

    def test_remove_whitelist(self):
        r = parse_command("移除白名单 张三")
        self.assertEqual(r["command"], "remove_whitelist")
        self.assertEqual(r["args"]["name"], "张三")

    def test_status(self):
        self.assertEqual(parse_command("状态")["command"], "show_status")

    def test_daily_report(self):
        self.assertEqual(parse_command("今日报告")["command"], "daily_report")

    def test_help(self):
        self.assertEqual(parse_command("帮助")["command"], "help")

    def test_rookie_review(self):
        r = parse_command("帮我看看：这个需求没给清楚")
        self.assertEqual(r["command"], "rookie_review")
        self.assertEqual(r["args"]["message"], "这个需求没给清楚")

    def test_rookie_task(self):
        r = parse_command("任务确认：完成产品分析报告")
        self.assertEqual(r["command"], "rookie_task")
        self.assertEqual(r["args"]["task"], "完成产品分析报告")

    def test_rookie_weekly(self):
        r = parse_command("写周报：本周做了A、B、C")
        self.assertEqual(r["command"], "rookie_weekly")

    def test_unknown(self):
        r = parse_command("随便说点什么")
        self.assertEqual(r["command"], "unknown")

    def test_set_context(self):
        r = parse_command("我在做：写Q2产品方案")
        self.assertEqual(r["command"], "set_context")
        self.assertEqual(r["args"]["context"], "写Q2产品方案")


class TestUserState(unittest.TestCase):
    def test_focus_lifecycle(self):
        user = get_user("test_lifecycle")
        self.assertFalse(user.is_focusing())

        user.start_focus(30, "写代码")
        self.assertTrue(user.is_focusing())
        self.assertEqual(user.work_context, "写代码")

        user.add_pending(PendingMessage(
            "m1", "张三", "u1", "群1", "你好", "P3", "archive", "", 0
        ))
        user.add_pending(PendingMessage(
            "m2", "李四", "u2", "群2", "项目进度", "P1", "queue", "", 0
        ))
        self.assertEqual(len(user.pending_messages), 2)
        self.assertEqual(user.daily_p3, 1)
        self.assertEqual(user.daily_p1, 1)

        stats = user.end_focus()
        self.assertFalse(user.is_focusing())
        self.assertEqual(stats["total_messages"], 2)
        self.assertEqual(stats["p1_count"], 1)
        self.assertEqual(stats["p3_count"], 1)

    def test_daily_reset(self):
        user = get_user("test_reset")
        user.daily_interrupt_count = 10
        user.daily_p0 = 1
        user.daily_p2 = 5
        user.reset_daily()
        self.assertEqual(user.daily_interrupt_count, 0)
        self.assertEqual(user.daily_p0, 0)
        self.assertEqual(user.daily_p2, 0)


if __name__ == "__main__":
    unittest.main()

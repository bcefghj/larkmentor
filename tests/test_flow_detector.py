"""Tests for Flow Detector module."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.user_state import get_user, FocusMode
from core.flow_detector import parse_command, get_status_text


class TestParseCommand(unittest.TestCase):
    def test_all_focus_variants(self):
        for cmd in [
            "开始专注",
            "focus",
            "专注",
            "开始保护",
            "进入勿扰",
            "勿扰开",
            "专注开",
        ]:
            r = parse_command(cmd)
            self.assertEqual(r["command"], "start_focus", f"Failed for: {cmd}")

    def test_all_end_variants(self):
        for cmd in [
            "结束专注",
            "done",
            "结束保护",
            "停止专注",
            "退出勿扰",
            "勿扰关",
            "专注关",
        ]:
            r = parse_command(cmd)
            self.assertEqual(r["command"], "end_focus", f"Failed for: {cmd}")

    def test_larkmentor_menu_aliases(self):
        self.assertEqual(parse_command("今日简报")["command"], "daily_report")
        self.assertEqual(parse_command("周度简报")["command"], "weekly_report")
        self.assertEqual(parse_command("组织记忆")["command"], "show_memory")

    def test_short_menu_five(self):
        """飞书菜单五字版：专注开 / 专注关 / 日报 / 周报 / 记忆"""
        self.assertEqual(parse_command("日报")["command"], "daily_report")
        self.assertEqual(parse_command("周报")["command"], "weekly_report")
        self.assertEqual(parse_command("记忆")["command"], "show_memory")

    def test_timed_disturb_chinese(self):
        r = parse_command("进入勿扰 25 分钟")
        self.assertEqual(r["command"], "start_focus")
        self.assertEqual(r["args"]["duration"], 25)

    def test_timed_focus_chinese(self):
        for minutes in [10, 25, 30, 60, 90, 120]:
            r = parse_command(f"专注{minutes}分钟")
            self.assertEqual(r["command"], "start_focus")
            self.assertEqual(r["args"]["duration"], minutes)

    def test_timed_focus_english(self):
        for minutes in [10, 25, 30, 60]:
            r = parse_command(f"focus {minutes}")
            self.assertEqual(r["command"], "start_focus")
            self.assertEqual(r["args"]["duration"], minutes)


class TestGetStatusText(unittest.TestCase):
    def test_normal_mode_status(self):
        user = get_user("test_status_normal")
        text = get_status_text(user)
        self.assertIn("普通模式", text)
        self.assertIn("开始专注", text)

    def test_focus_mode_status(self):
        user = get_user("test_status_focus")
        user.start_focus(30)
        text = get_status_text(user)
        self.assertIn("深度专注中", text)
        user.end_focus()


if __name__ == "__main__":
    unittest.main()

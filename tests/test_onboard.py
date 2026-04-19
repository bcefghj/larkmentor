"""Unit tests for MentorOnboard (8 cases)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def fresh_onboard(monkeypatch, tmp_path):
    from core.mentor import mentor_onboard as ob

    monkeypatch.setattr(ob, "_LOG_PATH", str(tmp_path / "onboard_state.json"))
    monkeypatch.setattr(ob, "_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ob, "_MEM", {})
    # Avoid touching real KB.
    monkeypatch.setattr(ob, "_ingest_into_kb", lambda sess: None)
    yield ob


def test_questions_are_5_and_aligned(fresh_onboard):
    qs = fresh_onboard.ONBOARDING_QUESTIONS
    assert len(qs) == 5
    # All ByteDance Mentor 4 dims represented.
    dims = {q["dim"] for q in qs}
    assert {"团队融入", "工作方法", "成长跟进", "专业技能"}.issubset(dims)


def test_start_creates_session(fresh_onboard):
    s = fresh_onboard.start("ou_a")
    assert s.open_id == "ou_a"
    assert s.completed is False
    assert s.next_question is not None


def test_submit_answer_advances(fresh_onboard):
    fresh_onboard.start("ou_b")
    s, done = fresh_onboard.submit_answer("ou_b", "测试团队")
    assert not done
    assert s.next_question is not None
    assert "team" in s.answers


def test_submit_5_answers_completes(fresh_onboard):
    fresh_onboard.start("ou_c")
    last_done = False
    for ans in ["市场部", "李明", "完成 KPI", "飞书多维表格", "写周报"]:
        _, last_done = fresh_onboard.submit_answer("ou_c", ans)
    assert last_done is True
    sess = fresh_onboard.get_session("ou_c")
    assert sess.completed is True
    assert len(sess.answers) == 5


def test_get_session_returns_none_for_unknown(fresh_onboard):
    assert fresh_onboard.get_session("ou_unknown") is None


def test_in_progress_returns_true_only_when_unfinished(fresh_onboard):
    assert fresh_onboard.is_in_progress("ou_d") is False
    fresh_onboard.start("ou_d")
    assert fresh_onboard.is_in_progress("ou_d") is True


def test_render_summary_includes_dim_tags(fresh_onboard):
    fresh_onboard.start("ou_e")
    fresh_onboard.submit_answer("ou_e", "运营部")
    sess = fresh_onboard.get_session("ou_e")
    md = fresh_onboard.render_summary(sess)
    assert "团队融入" in md
    assert "运营部" in md


def test_reset_clears_state(fresh_onboard):
    fresh_onboard.start("ou_f")
    fresh_onboard.submit_answer("ou_f", "x")
    assert fresh_onboard.is_in_progress("ou_f") is True
    fresh_onboard.reset("ou_f")
    assert fresh_onboard.get_session("ou_f") is None

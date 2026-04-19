"""Tests for mentor skills registration via SkillLoader (step9)"""

from __future__ import annotations

import pytest


@pytest.fixture
def fresh_runtime():
    """Reset both default_registry and default_loader to a fresh state."""
    from core.runtime import tool_registry, skill_loader
    from core.runtime.tool_registry import ToolRegistry
    from core.runtime.skill_loader import SkillLoader

    tool_registry._default = ToolRegistry()
    skill_loader._default = SkillLoader()
    yield


def test_register_all_creates_4_skills(fresh_runtime):
    from core.mentor.skills_init import register_all
    from core.runtime import default_loader

    stats = register_all()
    skills = default_loader().list_skills()
    skill_names = {s.name for s in skills}

    assert stats["skills_registered"] == 4
    assert {"mentor.write", "mentor.task", "mentor.review", "mentor.onboard"} == skill_names


def test_register_all_creates_5_tools(fresh_runtime):
    from core.mentor.skills_init import register_all
    from core.runtime import default_registry

    register_all()
    tool_names = {t.name for t in default_registry().list_tools()}
    assert "mentor.write" in tool_names
    assert "mentor.task" in tool_names
    assert "mentor.review" in tool_names
    assert "mentor.onboard.start" in tool_names
    assert "mentor.onboard.answer" in tool_names


def test_skill_triggers_route_to_correct_skill(fresh_runtime):
    from core.mentor.skills_init import register_all
    from core.runtime import default_loader

    register_all()
    loader = default_loader()

    assert loader.find_for_command("帮我看看这条消息怎么回").name == "mentor.write"
    assert loader.find_for_command("任务确认：方案什么时候要").name == "mentor.task"
    assert loader.find_for_command("写周报：本周做了 3 件事").name == "mentor.review"
    assert loader.find_for_command("重新入职").name == "mentor.onboard"


def test_disable_skill_works(fresh_runtime):
    from core.mentor.skills_init import register_all
    from core.runtime import default_loader

    register_all()
    loader = default_loader()
    assert loader.disable("mentor.task") is True
    assert loader.find_for_command("任务确认：方案什么时候要") is None
    assert loader.find_for_command("帮我看看怎么回").name == "mentor.write"


def test_skills_have_proper_permission_metadata(fresh_runtime):
    from core.mentor.skills_init import register_all
    from core.runtime import default_loader

    register_all()
    for s in default_loader().list_skills():
        assert s.permission == "DRAFT_ACTION"


def test_register_all_is_idempotent(fresh_runtime):
    from core.mentor.skills_init import register_all
    from core.runtime import default_loader

    register_all()
    register_all()
    assert len(default_loader().list_skills()) == 4

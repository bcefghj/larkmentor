"""Tests for core/runtime/ (Claude Code 7 支柱内层)"""

from __future__ import annotations

import pytest


def test_tool_registry_register_and_invoke():
    from core.runtime import ToolRegistry, ToolMetadata

    reg = ToolRegistry()

    def echo_handler(text: str) -> dict:
        return {"echo": text}

    reg.register(ToolMetadata(
        name="test.echo",
        description="echo back input",
        handler=echo_handler,
        permission="READ_ONLY",
    ))

    assert len(reg.list_tools()) == 1
    assert reg.get("test.echo").name == "test.echo"

    res = reg.invoke("test.echo", {"text": "hello"}, user_open_id="u1", skip_permission=True)
    assert res["ok"] is True
    assert res["data"] == {"echo": "hello"}
    assert "elapsed_ms" in res


def test_tool_registry_unknown_tool():
    from core.runtime import ToolRegistry

    reg = ToolRegistry()
    res = reg.invoke("nope.nope", {}, user_open_id="u1")
    assert res["ok"] is False
    assert res["stage"] == "lookup"


def test_tool_registry_args_mismatch():
    from core.runtime import ToolRegistry, ToolMetadata

    reg = ToolRegistry()

    def two_args(a: str, b: str) -> dict:
        return {"a": a, "b": b}

    reg.register(ToolMetadata(
        name="test.twoargs",
        description="",
        handler=two_args,
    ))
    res = reg.invoke("test.twoargs", {"a": "x"}, user_open_id="u1", skip_permission=True)
    assert res["ok"] is False
    assert res["stage"] == "invoke"


def test_tool_registry_rate_limit():
    from core.runtime import ToolRegistry, ToolMetadata

    reg = ToolRegistry()
    reg.register(ToolMetadata(
        name="test.fast",
        description="",
        handler=lambda: {"ok": True},
        permission="READ_ONLY",
        rate_limit_per_minute=2,
    ))
    r1 = reg.invoke("test.fast", {}, skip_permission=True)
    r2 = reg.invoke("test.fast", {}, skip_permission=True)
    r3 = reg.invoke("test.fast", {}, skip_permission=True)
    assert r1["ok"] and r2["ok"]
    assert r3["ok"] is False
    assert r3["stage"] == "rate_limit"


def test_tool_registry_stats():
    from core.runtime import ToolRegistry, ToolMetadata

    reg = ToolRegistry()
    reg.register(ToolMetadata(name="a", description="", handler=lambda: {}, skill="s1"))
    reg.register(ToolMetadata(name="b", description="", handler=lambda: {}, skill="s1"))
    reg.register(ToolMetadata(name="c", description="", handler=lambda: {}, skill="s2"))

    s = reg.stats()
    assert s["total_tools"] == 3
    assert s["tools_by_skill"]["s1"] == 2
    assert s["tools_by_skill"]["s2"] == 1


def test_skill_loader_register_and_find():
    from core.runtime import SkillLoader, SkillManifest

    loader = SkillLoader()
    loader.register(SkillManifest(
        name="mentor.write",
        description="",
        triggers=["帮我看看", "帮我写"],
        tools=["mentor.write"],
    ))
    loader.register(SkillManifest(
        name="mentor.task",
        triggers=["任务确认", "任务澄清"],
        tools=["mentor.task"],
    ))

    assert loader.find_for_command("帮我看看这条消息怎么回").name == "mentor.write"
    assert loader.find_for_command("任务确认：交付期是？").name == "mentor.task"
    assert loader.find_for_command("xx") is None


def test_skill_loader_enable_disable():
    from core.runtime import SkillLoader, SkillManifest

    loader = SkillLoader()
    loader.register(SkillManifest(name="s1", triggers=["s1"]))

    assert loader.find_for_command("s1") is not None
    loader.disable("s1")
    assert loader.find_for_command("s1") is None
    loader.enable("s1")
    assert loader.find_for_command("s1") is not None


def test_skill_manifest_to_from_dict():
    from core.runtime import SkillManifest

    m = SkillManifest(name="t", triggers=["a"], tools=["x.y"], system_prompt="hi")
    d = m.to_dict()
    m2 = SkillManifest.from_dict(d)
    assert m2.name == "t"
    assert m2.triggers == ["a"]
    assert m2.tools == ["x.y"]
    assert m2.system_prompt == "hi"


def test_permission_facade_returns_tuple():
    from core.runtime import PermissionFacade

    f = PermissionFacade()
    allowed, reason = f.check("shield.classify", "u1")
    assert isinstance(allowed, bool)
    assert isinstance(reason, str)


def test_hook_runtime_facade_smoke():
    from core.runtime import HookRuntime

    hr = HookRuntime()
    payload = {"content": "hi"}
    out = hr.fire_pre_classify(payload)
    assert "content" in out


def test_default_singletons():
    from core.runtime import (
        default_registry, default_loader,
        default_facade, default_hook_runtime,
    )

    assert default_registry() is default_registry()
    assert default_loader() is default_loader()
    assert default_facade() is default_facade()
    assert default_hook_runtime() is default_hook_runtime()

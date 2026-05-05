"""Tests for the DI container."""

import pytest
from core.container import Container


class TestContainer:
    def test_register_and_resolve(self):
        c = Container()
        c.register("test", lambda: {"value": 42})
        result = c.resolve("test")
        assert result["value"] == 42

    def test_singleton_behavior(self):
        c = Container()
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        c.register("test", factory)
        r1 = c.resolve("test")
        r2 = c.resolve("test")
        assert r1 is r2
        assert call_count == 1

    def test_override_for_testing(self):
        c = Container()
        c.register("test", lambda: "real")
        c.override("test", "mock")
        assert c.resolve("test") == "mock"

    def test_reset_clears_instances(self):
        c = Container()
        c.register("test", lambda: object())
        r1 = c.resolve("test")
        c.reset()
        r2 = c.resolve("test")
        assert r1 is not r2

    def test_resolve_unregistered_raises(self):
        c = Container()
        with pytest.raises(KeyError):
            c.resolve("nonexistent")

    def test_has_key(self):
        c = Container()
        assert not c.has("test")
        c.register("test", lambda: 1)
        assert c.has("test")

    def test_override_without_factory(self):
        c = Container()
        c.override("direct", {"direct_value": True})
        assert c.resolve("direct") == {"direct_value": True}

    def test_register_replaces_factory(self):
        c = Container()
        c.register("svc", lambda: "v1")
        assert c.resolve("svc") == "v1"
        c.register("svc", lambda: "v2")
        assert c.resolve("svc") == "v2"

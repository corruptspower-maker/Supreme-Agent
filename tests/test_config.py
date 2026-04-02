"""Tests for the configuration loader in src.utils.config."""

from __future__ import annotations

import pytest

from src.utils.config import _coerce, get_full_config, load_config


class TestLoadConfig:
    def test_loads_agent_yaml(self):
        cfg = load_config("agent")
        assert "agent" in cfg
        assert cfg["agent"]["name"] == "Executive Agent"

    def test_loads_models_yaml(self):
        cfg = load_config("models")
        assert "local" in cfg
        assert "escalation" in cfg

    def test_loads_tools_yaml(self):
        cfg = load_config("tools")
        assert "tools" in cfg
        assert "file_tool" in cfg["tools"]

    def test_loads_memory_yaml(self):
        cfg = load_config("memory")
        assert "memory" in cfg
        assert "conversation" in cfg["memory"]

    def test_loads_safety_yaml(self):
        cfg = load_config("safety")
        assert "safety" in cfg
        assert "forbidden_actions" in cfg["safety"]

    def test_loads_escalation_yaml(self):
        cfg = load_config("escalation")
        assert "escalation" in cfg
        assert "triggers" in cfg["escalation"]

    def test_loads_ui_yaml(self):
        cfg = load_config("ui")
        assert "ui" in cfg
        assert cfg["ui"]["theme"] == "dark"

    def test_loads_mcp_yaml(self):
        cfg = load_config("mcp")
        assert "mcp" in cfg
        assert "server" in cfg["mcp"]

    def test_missing_file_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="nonexistent"):
            load_config("nonexistent")

    def test_returns_dict(self):
        cfg = load_config("agent")
        assert isinstance(cfg, dict)


class TestGetFullConfig:
    def test_returns_dict(self):
        cfg = get_full_config()
        assert isinstance(cfg, dict)

    def test_all_sections_present(self):
        cfg = get_full_config()
        for section in ("agent", "local", "tools", "memory", "safety", "escalation", "ui", "mcp"):
            assert section in cfg, f"Missing section: {section}"

    def test_agent_section_has_name(self):
        cfg = get_full_config()
        assert cfg["agent"]["name"] == "Executive Agent"

    def test_env_override_applied(self, monkeypatch):
        monkeypatch.setenv("EA_AGENT__NAME", "Test Override Agent")
        cfg = get_full_config()
        assert cfg["agent"]["name"] == "Test Override Agent"

    def test_env_override_unknown_section_ignored(self, monkeypatch):
        monkeypatch.setenv("EA_UNKNOWN__KEY", "value")
        cfg = get_full_config()
        assert "unknown" not in cfg


class TestCoerce:
    def test_true_values(self):
        for val in ("true", "True", "TRUE", "yes", "Yes", "1"):
            assert _coerce(val) is True

    def test_false_values(self):
        for val in ("false", "False", "FALSE", "no", "No", "0"):
            assert _coerce(val) is False

    def test_integer(self):
        assert _coerce("42") == 42
        assert isinstance(_coerce("42"), int)

    def test_float(self):
        assert _coerce("3.14") == pytest.approx(3.14)
        assert isinstance(_coerce("3.14"), float)

    def test_string_fallback(self):
        assert _coerce("hello world") == "hello world"
        assert isinstance(_coerce("hello world"), str)

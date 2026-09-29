"""Settings: .env loading, environment precedence and required values."""
from __future__ import annotations

import pytest

from supragents.settings import Settings, SettingsError


def test_env_file_supplies_missing_values(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-environment")
    env = tmp_path / ".env"
    env.write_text('# comment\n\nDEEPSEEK_API_KEY="sk-from-file"\nDATABASE_URL=postgresql://from-file\n')
    settings = Settings.load(env)
    assert settings.deepseek_api_key == "sk-from-file"
    assert settings.database_url == "postgresql://from-environment"  # the environment wins


def test_missing_required_value_names_it(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(SettingsError, match="DEEPSEEK_API_KEY"):
        Settings.load(tmp_path / "absent.env").require("deepseek_api_key")

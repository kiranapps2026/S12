"""The repo-root .env is read reliably, including files saved by Windows tools."""
import pytest

from config import Settings


@pytest.mark.parametrize("prefix", ["", "﻿"])            # plain UTF-8 and UTF-8 with BOM
def test_settings_reads_the_key_with_or_without_a_bom(tmp_path, monkeypatch, prefix):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"{prefix}DEEPSEEK_API_KEY=sk-test-123\nDATABASE_URL=postgresql+asyncpg://u:p@h/db\n",
                   encoding="utf-8")
    s = Settings(_env_file=str(env))
    assert s.deepseek_api_key == "sk-test-123"
    assert s.database_url.endswith("@h/db")


def test_real_environment_variables_win_over_the_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-environment")
    assert Settings(_env_file=str(env)).deepseek_api_key == "from-environment"

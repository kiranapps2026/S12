"""Live DeepSeek test. Collected only when DEEPSEEK_API_KEY is set (never part of certification)."""
import os


def pytest_ignore_collect(collection_path, config):
    return not os.environ.get("DEEPSEEK_API_KEY") and collection_path.name.startswith("test_")

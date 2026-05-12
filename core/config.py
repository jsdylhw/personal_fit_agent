from pathlib import Path
from typing import Any

import yaml


DEFAULT_DATA_DIR = Path("data")
DEFAULT_CONFIG_PATH = Path("config.yaml")


def get_data_dir() -> Path:
    return DEFAULT_DATA_DIR


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件必须是 YAML object: {config_path}")
    return data


def get_agent_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    root = config if config is not None else load_config()
    agent_config = root.get("agent") or {}
    if not isinstance(agent_config, dict):
        raise ValueError("config.yaml 中的 agent 必须是 object")
    return {
        "provider": agent_config.get("provider", "anthropic"),
        "base_url": agent_config.get("base_url", ""),
        "api_key": agent_config.get("api_key", ""),
        "model": agent_config.get("model", ""),
        "max_tokens": int(agent_config.get("max_tokens", 1200)),
        "temperature": float(agent_config.get("temperature", 0.3)),
        "anthropic_version": agent_config.get("anthropic_version", "2023-06-01"),
    }


def ensure_data_dirs(data_dir: Path | None = None) -> dict[str, Path]:
    root = data_dir or get_data_dir()
    paths = {
        "root": root,
        "fit": root / "fit",
        "parsed": root / "parsed",
        "reports": root / "reports",
        "plots": root / "reports" / "plots",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths

"""配置加载:从 config.yaml 读取 Garmin/Strava/Agent/运动员 各项配置.

config.yaml 在 .gitignore 中,不会提交到仓库.
"""

from pathlib import Path
from typing import Any

import yaml

DEFAULT_DATA_DIR = Path("data")
DEFAULT_CONFIG_PATH = Path("config.yaml")


def get_data_dir() -> Path:
    return DEFAULT_DATA_DIR


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """加载完整的 config.yaml.

    Args:
        path: 配置文件路径.

    Returns:
        dict: 解析后的配置.文件不存在返回 {}.
    """
    config_path = Path(path)
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件必须是 YAML object: {config_path}")
    return data


def load_agent_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """从 config.yaml 中提取 agent: 块.

    用字符串行解析而非完整 YAML 再取 key,避免解析其他可能包含
    敏感值或特殊字符的顶层块.
    """
    config_path = Path(path)
    if not config_path.exists():
        return {}
    text = config_path.read_text(encoding="utf-8")
    block = _extract_top_level_yaml_block(text, "agent")
    if not block:
        return {}
    data = yaml.safe_load(block) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml 中的 agent 必须是 object")
    agent_config = data.get("agent") or {}
    if not isinstance(agent_config, dict):
        raise ValueError("config.yaml 中的 agent 必须是 object")
    return agent_config


def get_agent_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """获取标准化的 agent 配置,补全默认值.

    支持两种调用方式:
    - 无参:从 config.yaml 加载 agent 块.
    - 传 dict:从内存中的 config dict 提取 agent key.

    Args:
        config: 完整的 config dict(可选).

    Returns:
        dict: {provider, base_url, api_key, model, max_tokens, temperature,
               anthropic_version, timeout_seconds, max_retries}
    """
    agent_config = (
        (config.get("agent") or {}) if config is not None else load_agent_config()
    )
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
        "timeout_seconds": float(agent_config.get("timeout_seconds", 300)),
        "max_retries": int(agent_config.get("max_retries", 2)),
    }


def _extract_top_level_yaml_block(text: str, key: str) -> str:
    """从 YAML 文本中按缩进提取顶层 block.不依赖完整 YAML 解析."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")) and stripped == f"{key}:":
            start = index
            break
    if start is None:
        return ""

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            end = index
            break
    return "\n".join(lines[start:end])


def ensure_data_dirs(data_dir: Path | None = None) -> dict[str, Path]:
    """确保 data/ 目录存在.

    Returns:
        dict: {root} 路径映射.
    """
    root = data_dir or get_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    return {"root": root}

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config(config_dir: str = "configs") -> dict[str, Any]:
    env = os.getenv("ENV", "dev").lower()
    base_path = Path(config_dir) / "base.yaml"
    env_path = Path(config_dir) / f"{env}.yaml"

    with base_path.open("r", encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    if env_path.exists():
        with env_path.open("r", encoding="utf-8") as f:
            env_cfg: dict[str, Any] = yaml.safe_load(f) or {}
        cfg = deep_merge(cfg, env_cfg)

    cfg.setdefault("project", {})
    cfg.setdefault("service", {})
    cfg.setdefault("worker", {})
    cfg.setdefault("database", {})

    cfg["project"]["env"] = os.getenv("ENV", cfg["project"].get("env", "dev"))
    cfg["project"]["log_level"] = os.getenv("LOG_LEVEL", cfg["project"].get("log_level", "INFO"))

    cfg["service"]["host"] = os.getenv("HOST", cfg["service"].get("host", "0.0.0.0"))
    cfg["service"]["port"] = int(os.getenv("PORT", cfg["service"].get("port", 8000)))

    cfg["worker"]["enabled"] = _env_bool("WORKER_ENABLED", bool(cfg["worker"].get("enabled", True)))
    cfg["worker"]["interval_seconds"] = int(
        os.getenv("WORKER_INTERVAL_SECONDS", cfg["worker"].get("interval_seconds", 10))
    )
    cfg["database"]["url"] = os.getenv(
        "DATABASE_URL", cfg["database"].get("url", "sqlite:///./data/asignacion.db")
    )
    return cfg

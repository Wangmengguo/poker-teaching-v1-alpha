from __future__ import annotations

import json
import os
import time
from pathlib import Path

_CACHE: dict[str, tuple[dict, int, float, float]] = {}


def _resolve_base_dir() -> Path:
    # 优先外置目录
    ext = os.getenv("SUGGEST_CONFIG_DIR")
    if ext:
        p = Path(ext).expanduser().resolve()
        if p.exists():
            return p
    # 包内置目录
    return (Path(__file__).parent / "config").resolve()


def _version_from_file(p: Path) -> int:
    try:
        return int(p.stat().st_mtime)
    except Exception:
        return 0


def load_json_cached(rel_path: str, ttl_seconds: int = 60) -> tuple[dict, int]:
    """加载 JSON 配置，带 TTL + mtime 缓存；失败返回空字典与 version=0。

    返回：(data, config_version)
    """
    base = _resolve_base_dir()
    fp = (base / rel_path).resolve()
    key = str(fp)
    now = time.time()
    try:
        mtime = fp.stat().st_mtime
    except Exception:
        # 不存在时返回缓存（若有且未过期），否则空配置
        if key in _CACHE:
            data, ver, exp, cached_m = _CACHE[key]
            if now < exp:
                return data, ver
        return {}, 0

    # 命中缓存：同时检查 TTL 与 mtime
    if key in _CACHE:
        data, ver, exp, cached_m = _CACHE[key]
        if now < exp and cached_m == mtime:
            return data, ver

    try:
        with fp.open("r", encoding="utf-8") as f:
            data = json.load(f)
        ver = _version_from_file(fp)
    except Exception:
        # 解析失败：检查缓存是否有效（只检查TTL，不检查mtime，因为文件可能已被损坏）
        if key in _CACHE:
            cached_data, cached_ver, exp, cached_m = _CACHE[key]
            if now < exp:
                # 返回有效的缓存数据
                return cached_data, cached_ver
        # 无有效缓存或缓存过期：返回空配置
        data, ver = {}, 0

    _CACHE[key] = (data, ver, now + max(5, int(ttl_seconds or 0)), mtime)
    return data, ver


__all__ = ["load_json_cached"]

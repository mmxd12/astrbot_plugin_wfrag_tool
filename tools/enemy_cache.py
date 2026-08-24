"""敌人数据缓存与灰机 Wiki 查询。

查询顺序为本地缓存、灰机 Wiki、内置兜底数据。异步入口供 LLM 工具使用，
避免在 AstrBot 已运行的事件循环里调用 ``asyncio.run``。
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

CACHE_FILE = Path(__file__).parent / "enemy_cache.json"
CACHE_TTL = 86400
WIKI_SCRIPT = Path("/AstrBot/data/tools/huijiwiki_api.py")

ENEMY_ALIASES = {
    "虚空天使": "Void Angel", "天使": "Void Angel",
    "夜灵兆力使": "Teralyst", "兆力使": "Teralyst", "大傻": "Teralyst",
    "夜灵巨力使": "Gantulyst", "巨力使": "Gantulyst", "二傻": "Gantulyst",
    "夜灵水力使": "Hydrolyst", "水力使": "Hydrolyst", "三傻": "Teralyst",
    "三傻(夜灵)": "Hydrolyst",
    "堕落重型机枪手": "Corrupted Heavy Gunner", "重型机枪手": "Corrupted Heavy Gunner",
    "轰击者": "Corrupted Bombard",
}

# 字段保持为 build 计算器使用的 camelCase；Wiki 返回的 snake_case 会在
# _normalise_data 中统一转换。
DEFAULT_ENEMIES: dict[str, dict[str, Any]] = {
    "Corrupted Heavy Gunner": {
        "faction": "Corrupted", "healthType": "clonedFlesh", "armorType": "ferrite",
        "baseArmor": 500, "baseHealth": 700, "baseShield": 0, "baseLevel": 8,
        "weaknesses": ["腐蚀"], "resistances": [],
    },
    "Corrupted Bombard": {
        "faction": "Corrupted", "healthType": "clonedFlesh", "armorType": "alloy",
        "baseArmor": 500, "baseHealth": 700, "baseShield": 0, "baseLevel": 8,
        "weaknesses": ["辐射"], "resistances": [],
    },
    "Teralyst": {
        "faction": "Sentient", "healthType": "sentient", "armorType": "ferrite",
        "baseArmor": 692, "baseHealth": 1850750, "baseShield": 957492, "baseLevel": 1,
        "weaknesses": ["辐射", "冷", "电"], "resistances": ["腐蚀", "磁力", "冲击"],
        "phases": [{"name": "护盾阶段", "note": "需指挥官破盾"}, {"name": "本体阶段", "note": "常规武器输出"}],
        "mechanics": ["护盾免疫常规伤害", "弱点头部"],
    },
    "Void Angel": {
        "faction": "Zariman", "healthType": "sentient", "armorType": "alloy",
        "baseArmor": 200, "baseHealth": 500000, "baseShield": 250000, "baseLevel": 50,
        "weaknesses": ["虚空", "辐射"], "resistances": ["磁力"],
        "phases": [{"name": "实体阶段", "note": "常规武器输出"}, {"name": "虚空阶段", "note": "需指挥官转移"}],
        "mechanics": ["阶段机制", "虚空形态需指挥官"],
    },
}


def normalize_enemy_name(name: str) -> str:
    value = (name or "").strip()
    folded = value.casefold()
    for alias, standard in ENEMY_ALIASES.items():
        if folded == alias.casefold() or folded == standard.casefold():
            return standard
    return value


def _load_cache() -> dict[str, Any]:
    try:
        with CACHE_FILE.open(encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    try:
        with CACHE_FILE.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _normalise_data(data: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "health_type": "healthType", "armor_type": "armorType", "shield_type": "shieldType",
        "base_armor": "baseArmor", "base_health": "baseHealth", "base_shield": "baseShield",
        "base_level": "baseLevel",
    }
    return {aliases.get(key, key): value for key, value in data.items()}


def _parse_wiki_text(text: str) -> dict[str, Any]:
    """从灰机的渲染页文本提取明确出现的基础属性。"""
    result: dict[str, Any] = {}
    patterns = {
        "faction": r"派系\s*[:：]?\s*([^\s\n]+)",
        "baseHealth": r"生命\s*[:：]?\s*([\d,]+)",
        "baseShield": r"护盾\s*[:：]?\s*([\d,]+)",
        "baseArmor": r"护甲\s*[:：]?\s*([\d,]+)",
        "healthType": r"生命类型\s*[:：]?\s*([^\s\n]+)",
        "baseLevel": r"(?:基础等级|等级)\s*[:：]?\s*(\d+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).replace(",", "")
        result[key] = int(value) if key.startswith("base") else value
    faction = str(result.get("faction", "")).casefold()
    if "grineer" in faction or "grineer" in text.casefold():
        result.setdefault("armorType", "ferrite")
    elif "corpus" in faction or "corpus" in text.casefold():
        result.setdefault("armorType", "shield")
    elif "sentient" in faction or "Sentient" in text:
        result.setdefault("armorType", "alloy")
    elif "infested" in faction or "infested" in text.casefold():
        result.setdefault("armorType", "none")
    return result


async def _run_wiki(*args: str, timeout: float) -> str | None:
    """运行灰机脚本并在超时时可靠地回收子进程。"""
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(WIKI_SCRIPT), *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return None
        if process.returncode != 0:
            return None
        text = stdout.decode("utf-8", errors="replace").strip()
        if not text or any(token in text for token in ("Just a moment", "安全验证", "Cloudflare 验证未通过", "解析失败")):
            return None
        return text
    except (OSError, asyncio.SubprocessError):
        return None


async def _query_wiki(enemy_name: str) -> dict[str, Any] | None:
    if not WIKI_SCRIPT.is_file():
        return None
    # huijiwiki_api 的 search 输出一行一个标题，不能把整个结果行再拼接进 page。
    search = await _run_wiki("search", enemy_name, timeout=105)
    if not search:
        return None
    titles = [line.strip() for line in search.splitlines() if line.strip()]
    if not titles:
        return None
    preferred = next((title for title in titles if title.casefold() == enemy_name.casefold()), titles[0])
    page = await _run_wiki("page", preferred, timeout=105)
    return _parse_wiki_text(page) if page else None


def _default_for(name: str) -> dict[str, Any]:
    folded = name.casefold()
    for standard, data in DEFAULT_ENEMIES.items():
        if folded == standard.casefold() or folded in standard.casefold() or standard.casefold() in folded:
            return dict(data)
    return {}


async def resolve_enemy_async(name: str) -> dict[str, Any]:
    """异步解析敌人；可安全从 AstrBot 的 async 工具直接 await。"""
    standard = normalize_enemy_name(name)
    if not standard:
        return {}
    key = standard.casefold()
    cache = await asyncio.to_thread(_load_cache)
    entry = cache.get(key, {})
    if isinstance(entry, dict) and time.time() - float(entry.get("fetched_at", 0)) < CACHE_TTL:
        data = entry.get("data", {})
        return _normalise_data(data) if isinstance(data, dict) else {}

    wiki_data = await _query_wiki(standard)
    data = _default_for(standard)
    if wiki_data:
        data.update(_normalise_data(wiki_data))
    if data:
        cache[key] = {"data": data, "fetched_at": time.time()}
        await asyncio.to_thread(_save_cache, cache)
    return data


def resolve_enemy(name: str) -> dict[str, Any]:
    """同步兼容入口；在已有事件循环中请使用 resolve_enemy_async。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(resolve_enemy_async(name))
    # 不嵌套 asyncio.run；调用方在 async 环境必须 await 异步入口。
    return _default_for(normalize_enemy_name(name))

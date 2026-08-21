#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
紫卡（Riven）分析引擎
功能：OCR 识别紫卡截图 → 解析词条 → 计算评分区间
依赖：rapidocr-onnxruntime（已装）、wfapi 服务（倾向值）
"""

import json
import re
import urllib.request
import urllib.parse
from pathlib import Path

# ── 内置词条基础系数表（从 nyxbot CDN 数据提取） ──
TREND_DATA = {
 "伤害/近战伤害": {
  "archwing": 99.9,
  "melle": 164.7,
  "pistol": 219.6,
  "rifle": 165.0,
  "shotgun": 164.7
 },
 "几率不获得连击数": {
  "archwing": 0.0,
  "melle": 104.85,
  "pistol": 0.0,
  "rifle": 0.0,
  "shotgun": 0.0
 },
 "连击持续时间": {
  "archwing": 0.0,
  "melle": 8.1,
  "pistol": 0.0,
  "rifle": 0.0,
  "shotgun": 0.0
 },
 "初始连击": {
  "archwing": 0.0,
  "melle": 24.5,
  "pistol": 0.0,
  "rifle": 0.0,
  "shotgun": 0.0
 },
 "对Corpus伤害": {
  "archwing": 45.0,
  "melle": 45.0,
  "pistol": 45.0,
  "rifle": 45.0,
  "shotgun": 45.0
 },
 "对Grineer伤害": {
  "archwing": 45.0,
  "melle": 45.0,
  "pistol": 45.0,
  "rifle": 45.0,
  "shotgun": 45.0
 },
 "对Infested伤害": {
  "archwing": 45.0,
  "melle": 45.0,
  "pistol": 45.0,
  "rifle": 45.0,
  "shotgun": 45.0
 },
 "弹药最大值": {
  "archwing": 99.9,
  "melle": 0.0,
  "pistol": 90.0,
  "rifle": 49.95,
  "shotgun": 90.0
 },
 "弹匣容量": {
  "archwing": 60.3,
  "melle": 0.0,
  "pistol": 50.0,
  "rifle": 50.0,
  "shotgun": 50.0
 },
 "冰冻伤害": {
  "archwing": 119.7,
  "melle": 90.0,
  "pistol": 90.0,
  "rifle": 90.0,
  "shotgun": 90.0
 },
 "毒素伤害": {
  "archwing": 119.7,
  "melle": 90.0,
  "pistol": 90.0,
  "rifle": 90.0,
  "shotgun": 90.0
 },
 "电击伤害": {
  "archwing": 119.7,
  "melle": 90.0,
  "pistol": 90.0,
  "rifle": 90.0,
  "shotgun": 90.0
 },
 "火焰伤害": {
  "archwing": 119.7,
  "melle": 90.0,
  "pistol": 90.0,
  "rifle": 90.0,
  "shotgun": 90.0
 },
 "暴击几率": {
  "archwing": 99.9,
  "melle": 180.0,
  "pistol": 149.99,
  "rifle": 149.99,
  "shotgun": 90.0
 },
 "暴击伤害": {
  "archwing": 80.1,
  "melle": 90.0,
  "pistol": 90.0,
  "rifle": 120.0,
  "shotgun": 90.0
 },
 "冲击伤害": {
  "archwing": 90.0,
  "melle": 119.7,
  "pistol": 119.7,
  "rifle": 119.97,
  "shotgun": 119.97
 },
 "切割伤害": {
  "archwing": 90.0,
  "melle": 119.7,
  "pistol": 119.97,
  "rifle": 119.97,
  "shotgun": 119.97
 },
 "穿刺伤害": {
  "archwing": 90.0,
  "melle": 119.7,
  "pistol": 119.97,
  "rifle": 119.97,
  "shotgun": 119.97
 },
 "触发几率": {
  "archwing": 60.3,
  "melle": 90.0,
  "pistol": 90.0,
  "rifle": 90.0,
  "shotgun": 90.0
 },
 "触发时间": {
  "archwing": 99.99,
  "melle": 99.0,
  "pistol": 99.99,
  "rifle": 99.99,
  "shotgun": 99.0
 },
 "处决伤害": {
  "archwing": 0.0,
  "melle": 119.7,
  "pistol": 0.0,
  "rifle": 0.0,
  "shotgun": 0.0
 },
 "射速/攻击速度": {
  "archwing": 60.03,
  "melle": 54.9,
  "pistol": 74.7,
  "rifle": 60.03,
  "shotgun": 89.1
 },
 "投射物飞行速度": {
  "archwing": 0.0,
  "melle": 0.0,
  "pistol": 90.0,
  "rifle": 90.0,
  "shotgun": 89.1
 },
 "重击效率": {
  "archwing": 0.0,
  "melle": 73.44,
  "pistol": 0.0,
  "rifle": 0.0,
  "shotgun": 0.0
 },
 "多重射击": {
  "archwing": 60.3,
  "melle": 0.0,
  "pistol": 119.7,
  "rifle": 90.0,
  "shotgun": 119.7
 },
 "穿透": {
  "archwing": 2.7,
  "melle": 0.0,
  "pistol": 2.7,
  "rifle": 2.7,
  "shotgun": 2.7
 },
 "装填速度": {
  "archwing": 99.9,
  "melle": 0.0,
  "pistol": 50.0,
  "rifle": 50.0,
  "shotgun": 49.45
 },
 "攻击范围": {
  "archwing": 0.0,
  "melle": 1.94,
  "pistol": 0.0,
  "rifle": 0.0,
  "shotgun": 0.0
 },
 "后坐力": {
  "archwing": -90.0,
  "melle": 0.0,
  "pistol": -90.0,
  "rifle": -90.0,
  "shotgun": -90.0
 },
 "变焦": {
  "archwing": 59.99,
  "melle": 0.0,
  "pistol": 80.1,
  "rifle": 59.99,
  "shotgun": 0.0
 },
 "滑行攻击暴击几率": {
  "archwing": 0.0,
  "melle": 120.0,
  "pistol": 0.0,
  "rifle": 0.0,
  "shotgun": 0.0
 },
 "额外连击数几率": {
  "archwing": 0.0,
  "melle": 58.77,
  "pistol": 0.0,
  "rifle": 0.0,
  "shotgun": 0.0
 }
}

# ── 词条参数（effect → url_name） ──
TION_DATA = {
 "弹药上限": "ammo_maximum",
 "对Corpus伤害": "damage_vs_corpus",
 "对Grineer伤害": "damage_vs_grineer",
 "对Infested伤害": "damage_vs_infested",
 "冰冻伤害": "cold_damage",
 "初始连击数": "channeling_damage",
 "重击效率": "channeling_efficiency",
 "连击持续时间": "combo_duration",
 "暴击率": "critical_chance",
 "滑行攻击暴击率": "critical_chance_on_slide_attack",
 "暴击伤害": "critical_damage",
 "基础伤害": "base_damage_/_melee_damage",
 "电击伤害": "electric_damage",
 "火焰伤害": "heat_damage",
 "处决伤害": "finisher_damage",
 "射速/攻击速度": "fire_rate_/_attack_speed",
 "投射物飞行速度": "projectile_speed",
 "冲击伤害": "impact_damage",
 "弹匣容量": "magazine_capacity",
 "多重射击": "multishot",
 "毒素伤害": "toxin_damage",
 "穿透": "punch_through",
 "穿刺伤害": "puncture_damage",
 "装填速度": "reload_speed",
 "攻击范围": "range",
 "切割伤害": "slash_damage",
 "触发几率": "status_chance",
 "触发时间": "status_duration",
 "后坐力": "recoil",
 "变焦": "zoom",
 "额外连击数获取": "chance_to_gain_extra_combo_count",
 "的几率来获得连击数": "chance_to_gain_combo_count",
 "无": "none",
 "有": "has"
}

# ── 词条别名 ──
ALIAS_DATA = {
 "冰": "cold_damage",
 "爆率": "critical_chance",
 "爆伤": "critical_damage",
 "基伤": "base_damage_/_melee_damage",
 "电": "electric_damage",
 "火": "heat_damage",
 "冲": "impact_damage",
 "多重": "multishot",
 "毒": "toxin_damage",
 "范围": "range",
 "切割": "slash_damage",
 "触发": "status_chance",
 "C": "damage_vs_corpus",
 "G": "damage_vs_grineer",
 "I": "damage_vs_infested",
 "暴伤": "critical_damage",
 "暴率": "critical_chance"
}

# 词条中英文映射（用于 OCR 识别和展示）
# 自动从 TION_DATA + ALIAS_DATA 生成
ATTR_CN_MAP = {}
for effect, url_name in TION_DATA.items():
    ATTR_CN_MAP[effect] = url_name
for cn, en in ALIAS_DATA.items():
    if cn not in ATTR_CN_MAP:
        ATTR_CN_MAP[cn] = en
# 额外补充常用别名
ATTR_CN_MAP.update({
    "暴击率": "critical_chance", "暴率": "critical_chance",
    "暴伤": "critical_damage", "基伤": "base_damage_/_melee_damage",
    "多重": "multishot", "触发": "status_chance",
    "攻速": "fire_rate_/_attack_speed", "射速": "fire_rate_/_attack_speed",
    "换弹": "reload_speed", "弹匣": "magazine_capacity",
    "备弹": "ammo_maximum", "病毒": "toxin_damage",
    "腐蚀": "toxin_damage", "火": "heat_damage",
    "冰": "cold_damage", "电": "electric_damage",
    "毒": "toxin_damage", "冲击": "impact_damage",
    "切割": "slash_damage", "穿刺": "puncture_damage",
    "范围": "range", "穿透": "punch_through",
    "变焦": "zoom", "弹速": "projectile_speed",
    "对G": "damage_vs_grineer", "对C": "damage_vs_corpus", "对I": "damage_vs_infested",
    # 游戏内卡面全称（TION_DATA 用的是简称，OCR 读到的是这些）
    "暴击几率": "critical_chance",
    "滑行攻击暴击几率": "critical_chance_on_slide_attack",
    "触发几率": "status_chance",
    "触发时间": "status_duration",
    "多重射击": "multishot",
    "射击速度": "fire_rate_/_attack_speed",
    "攻击速度": "fire_rate_/_attack_speed",
    "换弹速度": "reload_speed",
    "弹匣容量": "magazine_capacity",
    "弹药最大值": "ammo_maximum",
    "投射物速度": "projectile_speed",
    "后坐力": "recoil",
    "后座力": "recoil",
    "毒素伤害": "toxin_damage",
    "火焰伤害": "heat_damage",
    "寒冷伤害": "cold_damage",
    "冰冻伤害": "cold_damage",
})

# 反向映射（url_name → 中文名，用于展示）
ATTR_EN_MAP = {v: k for k, v in ATTR_CN_MAP.items()}
ATTR_EN_MAP.update({
    "critical_chance": "暴击几率", "critical_damage": "暴击伤害",
    "base_damage_/_melee_damage": "基础伤害", "multishot": "多重射击",
    "status_chance": "触发几率", "fire_rate_/_attack_speed": "射速",
    "magazine_capacity": "弹匣容量", "ammo_maximum": "弹药最大值",
    "reload_speed": "装填速度", "punch_through": "穿透",
    "zoom": "变焦", "heat_damage": "火焰伤害", "cold_damage": "冰冻伤害",
    "toxin_damage": "毒素伤害", "electric_damage": "电击伤害",
    "impact_damage": "冲击伤害", "puncture_damage": "穿刺伤害",
    "slash_damage": "切割伤害", "projectile_speed": "弹速",
    "combo_duration": "连击持续时间", "range": "范围",
    "recoil": "后坐力", "status_duration": "触发持续时间",
    "damage_vs_grineer": "对Grineer伤害", "damage_vs_corpus": "对Corpus伤害",
    "damage_vs_infested": "对Infested伤害",
})


def get_base_value(attr_name: str, riven_type: str) -> float:
    """获取词条基础系数（按词条名 + 武器类型）"""
    if riven_type == "melee":
        riven_type = "melle"
    if attr_name in TREND_DATA:
        return TREND_DATA[attr_name].get(riven_type, 0)
    for key, val in TREND_DATA.items():
        if attr_name in key or key in attr_name:
            return val.get(riven_type, 0)
    for effect, url_name in TION_DATA.items():
        if attr_name == effect or attr_name in effect or effect in attr_name:
            return TREND_DATA.get(effect, {}).get(riven_type, 0)
    return 0




# ── 紫卡武器表（en/zh/rivenType/disposition，442 把） ──
# OCR 对中文常认错字（鳄神→鲲神、冰凇→冰淞），靠这张表做模糊纠正 +
# 直接拿到倾向值，省掉一次网络请求。用 tools/refresh_riven_weapons.py 刷新。
WEAPONS_FILE = Path(__file__).parent / "riven_weapons.json"
_WEAPONS: dict | None = None


def _weapons() -> dict:
    global _WEAPONS
    if _WEAPONS is None:
        try:
            with open(WEAPONS_FILE, encoding="utf-8") as f:
                _WEAPONS = json.load(f)
        except Exception:
            _WEAPONS = {}
    return _WEAPONS


def resolve_weapon(name: str, riven_type_hint: str | None = None) -> dict | None:
    """把 OCR 出来的武器名（中文可能有错字，英文一般准）解析成武器表条目。

    顺序：英文精确 → 中文精确 → 英文模糊 → 中文模糊。
    riven_type_hint 用来消歧同名候选（鳄神 shotgun vs 月神 rifle）。
    返回 {en, zh, rivenType, disposition, slug, matched_by, score} 或 None。
    """
    if not name:
        return None
    table = _weapons()
    if not table:
        return None
    q = name.strip()

    # 英文精确（大小写不敏感）
    for en, v in table.items():
        if en.lower() == q.lower():
            return {**v, "matched_by": "en", "score": 1.0}
    # 中文精确
    for v in table.values():
        if v["zh"] == q:
            return {**v, "matched_by": "zh", "score": 1.0}

    # 英文子串：Ignis Wraith / Boltor Prime 这类变体不单列紫卡条目，
    # 与基础武器共用紫卡，取最长匹配的基础名。
    subs = [v for v in table.values()
            if len(v["en"]) >= 4 and v["en"].lower() in q.lower()]
    if subs:
        hit = max(subs, key=lambda v: len(v["en"]))
        return {**hit, "matched_by": "en:sub", "score": 1.0}

    # 模糊：英文优先（OCR 对英文准），中文兜底
    import difflib

    def best(field: str):
        scored = []
        for v in table.values():
            if riven_type_hint and v.get("rivenType") != riven_type_hint:
                continue
            s = difflib.SequenceMatcher(None, q.lower(), v[field].lower()).ratio()
            scored.append((s, v))
        if not scored:
            return 0.0, []
        top = max(s for s, _ in scored)
        return top, [v for s, v in scored if s == top]

    for field, floor in (("en", 0.6), ("zh", 0.45)):
        score, hits = best(field)
        if hits and score >= floor:
            out = {**hits[0], "matched_by": f"{field}~", "score": round(score, 3)}
            if len(hits) > 1:
                # 中文单字错认常出现平票（鲲神 → 鳄神/月神 同分），交给调用方提示用户
                out["ambiguous"] = [h["zh"] for h in hits]
            return out
    return None


# ── 倾向值缓存（本地 JSON，避免重复请求） ──
CACHE_FILE = Path(__file__).parent / "riven_disposition_cache.json"

def _load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_cache(data: dict):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

def fetch_disposition(weapon_name: str) -> float | None:
    """带缓存的紫卡倾向值查询（先查本地武器表，再走网络）"""
    hit = resolve_weapon(weapon_name)
    if hit and hit.get("disposition"):
        return hit["disposition"]
    cache = _load_cache()
    key = weapon_name.strip().lower()
    if key in cache:
        return cache[key].get("disposition")
    try:
        url = "http://111.170.14.106:18511/wmr/" + urllib.parse.quote(weapon_name)
        req = urllib.request.Request(url, headers={"User-Agent": "riven-analyse/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        word = data.get("word") or {}
        disp = word.get("disposition")
        rtype = word.get("rivenType") or word.get("type", "rifle")
        if disp is not None:
            cache[key] = {"disposition": disp, "rivenType": rtype}
            _save_cache(cache)
        return disp
    except Exception:
        return None


def get_riven_type(weapon_name: str) -> str | None:
    """带缓存的紫卡类型查询（先查本地武器表，再走网络）"""
    hit = resolve_weapon(weapon_name)
    if hit and hit.get("rivenType"):
        return hit["rivenType"]
    cache = _load_cache()
    key = weapon_name.strip().lower()
    if key in cache:
        return cache[key].get("rivenType")
    # 触发 fetch_disposition 来填充缓存
    fetch_disposition(weapon_name)
    cache = _load_cache()
    return cache.get(key, {}).get("rivenType")


def compute_low_high(base_val: float, omega: float, pos_count: int, has_neg: bool) -> tuple:
    """
    计算低/高区间（移植 nyxbot RivenAnalyseService._compute_low_high）
    返回 (low, high)
    """
    if pos_count == 2 and not has_neg:
        factor = 0.99
    elif pos_count == 2 and has_neg:
        factor = 1.2375
    elif pos_count == 3 and not has_neg:
        factor = 0.75
    elif pos_count == 3 and has_neg:
        factor = 0.9375
    else:
        factor = 1.0

    low = round(0.9 * base_val * omega * factor, 4)
    high = round(1.1 * base_val * omega * factor, 4)
    return low, high


def compute_neg_low_high(pos_count: int, has_neg: bool) -> tuple:
    """计算负面词条的修正区间"""
    if pos_count == 2 and has_neg:
        factor = -0.495
    elif pos_count == 3 and has_neg:
        factor = -0.75
    else:
        return (0, 0)
    # 负面词条不做 base_val 和 omega 乘法（直接从系数算）
    low = round(0.9 * factor * 100, 2)
    high = round(1.1 * factor * 100, 2)
    return low, high


def dot_from_omega(omega: float) -> str:
    """倾向值转星数"""
    if omega < 0.7:
        return "●○○○○"
    elif omega < 0.9:
        return "●●○○○"
    elif omega < 1.15:
        return "●●●○○"
    elif omega < 1.3:
        return "●●●●○"
    else:
        return "●●●●●"


def _clean_attr_name(s: str) -> str:
    """清掉词条名周围的标点/残留百分号，空白视为无名。"""
    return (s or "").strip().strip("%:：,，.。、|/ ").strip()


def parse_ocr_text(text: str) -> dict:
    """
    解析 OCR 识别文本，提取武器名和词条
    返回: {weapon_name, riven_type, attrs: [{name, value, positive, url_name}], pos_count, neg_count}
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    result = {"weapon_name": "", "attrs": [], "pos_count": 0, "neg_count": 0}

    # 从文本中提取武器名。卡面第一行形如「鳄神 Vexi-critadra」——
    # 后半是紫卡的随机后缀名（由词条词根拼成），跟武器英文名无关，直接丢掉。
    # OCR 认中文常错字（鳄神→鲲神、冰凇→冰淞），交给 resolve_weapon 按 442
    # 把紫卡武器表模糊纠正。
    # 注意：OCR 可能把卡面上方槽位/装饰文字（如 "武器18y"）误识别为武器名，
    # 因此遍历所有行，取 resolve_weapon 匹配分最高的那一行作为武器名。
    best_hit = None
    best_line = ""
    for line in lines:
        cleaned = re.sub(r"紫卡|Riven\s*Mod", "", line, flags=re.I).strip()
        # 掐掉随机后缀名：连字符英文词（Vexi-critadra / Igni-visican）
        cleaned = re.sub(r"\s*[A-Za-z]+-[A-Za-z]+\s*$", "", cleaned).strip()
        if not cleaned or len(cleaned) < 2:
            continue
        hit = resolve_weapon(cleaned)
        if hit and hit.get("score", 0) >= (best_hit or {}).get("score", 0):
            best_hit = hit
            best_line = cleaned
    if best_hit:
        result["weapon_name"] = best_hit["zh"]
        result["weapon_en"] = best_hit["en"]
        result["riven_type"] = best_hit["rivenType"]
        result["weapon_match"] = {
            "input": best_line, "by": best_hit["matched_by"], "score": best_hit["score"],
        }
        if best_hit.get("ambiguous"):
            result["weapon_match"]["ambiguous"] = best_hit["ambiguous"]
    else:
        # 兜底：第一行非空当作武器名
        for line in lines:
            cleaned = re.sub(r"紫卡|Riven\s*Mod", "", line, flags=re.I).strip()
            cleaned = re.sub(r"\s*[A-Za-z]+-[A-Za-z]+\s*$", "", cleaned).strip()
            if cleaned and len(cleaned) >= 2:
                result["weapon_name"] = cleaned
                break

    # 提取词条（正负值）。两种排版都要支持：
    #   卡面（游戏内）：「+72% 电击伤害」——数值在前
    #   手输/列表：「暴击几率 +119.2%」——名字在前
    # 一行里也可能挤多条，用 finditer 逐个切片。
    for line in lines:
        line = line.strip()
        matches = list(re.finditer(r"([+\-x])\s*([\d.]+)%?", line))
        # 先定行的排版：首个数值前面有文字 = 名字在前（手输/列表），
        # 否则 = 数值在前（游戏卡面）。整行统一，避免「多重射击 +111.7% 火焰伤害 +115.6%」
        # 这种一行多条时把名字错配给相邻词条。
        name_first = bool(matches) and bool(_clean_attr_name(line[:matches[0].start()]))
        for i, m in enumerate(matches):
            sign = m.group(1)
            value = float(m.group(2))
            positive = sign == "+"

            if name_first:
                seg = (line[:m.start()] if i == 0
                       else line[matches[i - 1].end():m.start()])
            else:
                seg = (line[m.end():] if i == len(matches) - 1
                       else line[m.end():matches[i + 1].start()])
            name_text = _clean_attr_name(seg)

            url_name = ATTR_CN_MAP.get(name_text, name_text)

            attr = {
                "name": name_text,
                "value": value,
                "positive": positive,
                "url_name": url_name,
            }
            result["attrs"].append(attr)
            if positive:
                result["pos_count"] += 1
            else:
                result["neg_count"] += 1

    # 翻译映射：确保 url_name 是英文，name 是中文
    for attr in result["attrs"]:
        name = attr["name"]
        # 如果 name 是英文，尝试翻译成中文
        if name in ATTR_EN_MAP:
            attr["name"] = ATTR_EN_MAP[name]
        # 确保 url_name 是英文
        if name in ATTR_CN_MAP:
            attr["url_name"] = ATTR_CN_MAP[name]
        else:
            # name 本身可能是英文
            attr["url_name"] = name

    return result



# 武器类型中文名映射
RIVEN_TYPE_MAP = {
    "rifle": "步枪", "pistol": "手枪", "shotgun": "霰弹枪",
    "melle": "近战",
    "melee": "近战", "archwing": "Archwing",
}


def analyse_riven(weapon_name: str, attrs: list, riven_type: str = None, omega: float = None, riven_name: str = None) -> dict:
    """分析紫卡属性
    返回: {weapon_name, riven_type, omega, dot, attrs_analysis, summary}
    """
    if omega is None:
        omega = fetch_disposition(weapon_name) or 1.0
    if riven_type is None:
        riven_type = get_riven_type(weapon_name) or "rifle"

    pos_count = sum(1 for a in attrs if a["positive"])
    has_neg = any(not a["positive"] for a in attrs)

    attrs_analysis = []
    for attr in attrs:
        # 每個詞條單獨獲取 base_val
        base_val = get_base_value(attr["name"], riven_type)
        
        # 計算 low/high (參考 nyxbot _compute_low_high)
        if pos_count == 2 and not has_neg:
            factor = 0.99
        elif pos_count == 2 and has_neg:
            factor = 1.2375 if attr["positive"] else -0.495
        elif pos_count == 3 and not has_neg:
            factor = 0.75
        elif pos_count == 3 and has_neg:
            factor = 0.9375 if attr["positive"] else -0.75
        else:
            # 4 詞條或其他情況，保守處理
            factor = 1.0 if attr["positive"] else -0.5
        
        low = round(0.9 * base_val * omega * factor, 4)
        high = round(1.1 * base_val * omega * factor, 4)
        
        # 計算偏差 (參考 nyxbot _attr_diff)
        median = (low + high) / 2
        attr_value = attr["value"]
        
        # 特殊處理歧視詞條（對Corpus伤害等）
        if any(k in attr["name"] for k in ["对Corpus伤害", "对Grineer伤害", "对Infested伤害"]):
            # x1.39 对Grineer伤害 这类歧视词条走 (abs-1)*100 特殊公式
            abs_attr = abs(attr_value)
            if abs_attr > 1:
                adjusted_value = (abs_attr - 1) * 100
            else:
                adjusted_value = 100 - abs_attr * 100
            # 計算偏差時用調整後的值
            if median != 0:
                diff_pct = round((adjusted_value - median) / median * 100, 2)
            else:
                diff_pct = 0
            diff_str = f"{diff_pct:+.2f}%"
        else:
            # 普通詞條
            if median != 0:
                diff_pct = round((attr_value - median) / median * 100, 2)
            else:
                diff_pct = 0
            diff_str = f"{diff_pct:+.2f}%"
        
        attrs_analysis.append({
            "name": attr["name"],
            "url_name": attr.get("url_name", attr["name"]),
            "value": attr_value,
            "positive": attr["positive"],
            "low": round(low, 2),
            "high": round(high, 2),
            "mid": round(median, 2),
            "diff": diff_str,
        })

    dot = dot_from_omega(omega)
    rtype_cn = RIVEN_TYPE_MAP.get(riven_type, riven_type)

    # 生成概要
    # 第一行显示武器名+原名称（如有）
    # riven_name 从参数传入
    title = f"🔫 {weapon_name}（{riven_name}）" if riven_name else f"🔫 {weapon_name}（{rtype_cn}紫卡）"
    lines = [title]
    lines.append(f"倾向 {omega} | {dot}")
    lines.append("")
    for a in attrs_analysis:
        sign = "+" if a["positive"] else "-"
        cn = ATTR_EN_MAP.get(a["url_name"], a["name"])
        lines.append(f"  {sign}{cn} {a['value']}")
        lines.append(f"    区间 {a['low']}~{a['high']} | 中位 {a['mid']} | 偏差 {a['diff']}")
    lines.append("")
    if has_neg:
        lines.append("💡 负面词条会提升正面词条的上限！")
    lines.append(f"📊 参考：{rtype_cn}紫卡 {pos_count}正{'1负' if has_neg else '0负'}")

    return {
        "weapon_name": weapon_name,
        "riven_type": riven_type,
        "omega": omega,
        "dot": dot,
        "base_val": get_base_value(list(attrs_analysis)[0]["name"], riven_type) if attrs_analysis else 0,  # 取第一個詞條的 base_val 作為概要顯示
        "attrs": attrs_analysis,
        "summary": "\n".join(lines),
    }
def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="紫卡分析工具")
    parser.add_argument("--image", "-i", help="紫卡截图路径")
    parser.add_argument("--weapon", "-w", help="武器名（可选，不指定则从 OCR 识别）")
    parser.add_argument("--text", "-t", help="直接输入词条文本（跳过 OCR）")
    args = parser.parse_args()

    if args.image:
        # OCR 识别
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        result, elapse = engine(args.image)
        if not result:
            print("❌ OCR 识别失败，请检查图片")
            return
        text = "\n".join([item[1] for item in result])
        print(f"📝 OCR 识别结果: {text}")
        parsed = parse_ocr_text(text)
    elif args.text:
        parsed = parse_ocr_text(args.text)
    else:
        # 交互模式
        print("🃏 紫卡分析工具")
        print("请输入词条文本（每行一个）或直接贴截图路径")
        weapon = args.weapon or input("武器名: ").strip()
        print("输入词条（格式: 暴击几率 +119.2%），空行结束:")
        lines = []
        while True:
            line = input().strip()
            if not line:
                break
            lines.append(line)
        parsed = parse_ocr_text("\n".join(lines))
        if weapon:
            parsed["weapon_name"] = weapon

    if not parsed["attrs"]:
        print("❌ 未识别到词条数据")
        return

    result = analyse_riven(
        weapon_name=parsed["weapon_name"],
        attrs=parsed["attrs"],
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
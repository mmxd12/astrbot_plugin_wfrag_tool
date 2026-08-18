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
    if attr_name in TREND_DATA:
        return TREND_DATA[attr_name].get(riven_type, 0)
    for key, val in TREND_DATA.items():
        if attr_name in key or key in attr_name:
            return val.get(riven_type, 0)
    for effect, url_name in TION_DATA.items():
        if attr_name == effect or attr_name in effect or effect in attr_name:
            return TREND_DATA.get(effect, {}).get(riven_type, 0)
    return 0




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
    """带缓存的紫卡倾向值查询"""
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
    """带缓存的紫卡类型查询"""
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


def parse_ocr_text(text: str) -> dict:
    """
    解析 OCR 识别文本，提取武器名和词条
    返回: {weapon_name, riven_type, attrs: [{name, value, positive, url_name}], pos_count, neg_count}
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    result = {"weapon_name": "", "attrs": [], "pos_count": 0, "neg_count": 0}

    # 从文本中提取武器名（第一行可能包含武器名）
    for line in lines[:3]:
        # 常见紫卡截图格式：武器名 + "紫卡" / 武器名单独一行
        cleaned = re.sub(r"[紫卡RivenMod\s\-]", "", line).strip()
        if cleaned and len(cleaned) > 1:
            result["weapon_name"] = cleaned
            break

    # 提取词条（正负值）
    for line in lines:
        line = line.strip()
        # 匹配 "+数字" 或 "-数字" 格式的词条
        m = re.search(r"([+\-])([\d.]+)%?", line)
        if not m:
            continue
        sign = m.group(1)
        value = float(m.group(2))
        positive = sign == "+"

        # 提取词条名（数值前面的文字）
        name_text = line[:m.start()].strip().rstrip(":：")
        if not name_text:
            name_text = line[:m.start()].strip()

        # 匹配中文词条名
        # 词条名可能是前缀+效果名，如 "暴击几率 +119.2%"
        # 或 "基础伤害 +165.4" 等
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

    return result



# 武器类型中文名映射
RIVEN_TYPE_MAP = {
    "rifle": "步枪", "pistol": "手枪", "shotgun": "霰弹枪",
    "melle": "近战", "archwing": "Archwing",
}


def analyse_riven(weapon_name: str, attrs: list, riven_type: str = None, omega: float = None) -> dict:
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
    lines = [f"🔫 {weapon_name}（{rtype_cn}紫卡）"]
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
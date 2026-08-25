"""Warframe 作战环境/场景数据 - 用于多环境配卡

每个环境包含：敌人构成、推荐元素、生存需求、特殊机制
"""
ENVIRONMENTS = {
    "科研": {
        "aliases": ["科研", "实验室", "科研站"],
        "enemy_faction": "Grineer",
        "enemy_level": 60,
        "armor_heavy": True,
        "recommended": ["腐蚀", "病毒"],
        "notes": "Grineer 重甲多，建议腐蚀剥甲 + 高爆发",
    },
    "钢铁之路": {
        "aliases": ["钢路", "钢铁", "steel path"],
        "enemy_faction": "混合",
        "enemy_level": 150,
        "armor_heavy": True,
        "recommended": ["腐蚀", "辐射"],
        "notes": "敌人等级 150+，护甲翻倍，需要装甲穿透和高 DPS",
    },
    "仲裁": {
        "aliases": ["仲裁", "arbitration"],
        "enemy_faction": "混合",
        "enemy_level": 100,
        "armor_heavy": True,
        "recommended": ["腐蚀", "病毒"],
        "notes": "仲裁敌人带护罩，需要无视护罩或高爆发",
    },
    "夜灵": {
        "aliases": ["夜灵", "三傻", "兆力使", "eidolon"],
        "enemy_faction": "Sentient",
        "enemy_level": 50,
        "armor_heavy": False,
        "shield_heavy": True,
        "recommended": ["辐射", "冷"],
        "notes": "夜灵有护盾层，需要指挥官破盾 + 辐射输出本体",
    },
    "指数": {
        "aliases": ["指数", "指数之场", "index"],
        "enemy_faction": "Corpus",
        "enemy_level": 80,
        "armor_heavy": False,
        "shield_heavy": True,
        "recommended": ["磁力", "毒"],
        "notes": "Corpus 护盾厚，磁力对护盾 + 毒穿盾伤害",
    },
    "扎里曼": {
        "aliases": ["扎里曼", "天使", "zariman"],
        "enemy_faction": "混合",
        "enemy_level": 100,
        "armor_heavy": True,
        "recommended": ["腐蚀", "辐射"],
        "notes": "扎里曼混合敌人 + 虚空天使，需要全能配装",
    },
    "九重天": {
        "aliases": ["九重天", "航道星舰", "railjack"],
        "enemy_faction": "Grineer",
        "enemy_level": 70,
        "armor_heavy": True,
        "recommended": ["腐蚀", "辐射"],
        "notes": "九重天舰内战斗，敌人密度高",
    },
    "平原": {
        "aliases": ["平原", "地球平原", "夜灵平野"],
        "enemy_faction": "Grineer",
        "enemy_level": 40,
        "armor_heavy": True,
        "recommended": ["腐蚀"],
        "notes": "开放平原，敌人分散，需要射程",
    },
    "墓地": {
        "aliases": ["墓地", "墓垒", "火卫二"],
        "enemy_faction": "Infested",
        "enemy_level": 60,
        "armor_heavy": False,
        "recommended": ["火", "病毒"],
        "notes": "Infested 无护甲但有回血，火+病毒最优",
    },
    "赤毒": {
        "aliases": ["赤毒", "赤毒要塞", "kuva"],
        "enemy_faction": "Grineer",
        "enemy_level": 90,
        "armor_heavy": True,
        "recommended": ["腐蚀", "病毒"],
        "notes": "赤毒要塞 Grineer 重甲，腐蚀剥甲",
    },
    "虚空": {
        "aliases": ["虚空", "虚空裂缝", "void"],
        "enemy_faction": "Corrupted",
        "enemy_level": 50,
        "armor_heavy": True,
        "recommended": ["腐蚀", "辐射"],
        "notes": "Corrupted 混合敌人，腐蚀+辐射通吃",
    },
    "警报": {
        "aliases": ["警报", "悬赏"],
        "enemy_faction": "混合",
        "enemy_level": 40,
        "armor_heavy": False,
        "recommended": ["通用"],
        "notes": "通用悬赏，均衡配装即可",
    },
}

def resolve_environment(name: str) -> dict | None:
    """按名称/别名解析环境数据（支持包含匹配：'时光科研'→'科研'）"""
    name = (name or "").strip().lower()
    # 精确匹配
    for env, data in ENVIRONMENTS.items():
        if name == env.lower():
            return {**data, "name": env}
        for a in data.get("aliases", []):
            if name == a.lower():
                return {**data, "name": env}
    # 包含匹配：输入包含环境名（如"时光科研"包含"科研"）
    for env, data in ENVIRONMENTS.items():
        if env.lower() in name:
            return {**data, "name": env}
        for a in data.get("aliases", []):
            if a.lower() in name and len(a) >= 2:
                return {**data, "name": env}
    return None

def get_environment_recommendation(env_data: dict) -> str:
    """根据环境生成配装建议文本"""
    lines = [
        f"🌍 环境：{env_data.get('name','?')}",
        f"敌人：{env_data.get('enemy_faction','混合')} | 等级约 {env_data.get('enemy_level','?')}",
    ]
    rec = env_data.get("recommended", [])
    if rec:
        lines.append(f"推荐属性：{'、'.join(rec)}")
    if env_data.get("armor_heavy"):
        lines.append("⚠️ 重甲敌人多，优先护甲穿透")
    if env_data.get("shield_heavy"):
        lines.append("⚠️ 护盾敌人多，优先对盾伤害")
    if env_data.get("notes"):
        lines.append(f"💡 {env_data['notes']}")
    return "\n".join(lines)

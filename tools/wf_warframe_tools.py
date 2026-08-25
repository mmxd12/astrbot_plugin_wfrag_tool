"""战甲配装工具 - 本地核心MOD + /mods API 动态补齐 + WFCD 战甲面板
集成到 astrbot_plugin_wfrag_tool 插件：
- wf_recommend_warframe_build: 战甲配装推荐（流派 + 敌人感知）
"""
import asyncio
import json
import os
import time
import urllib.request

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter

try:
    from .enemy_cache import resolve_enemy_async
except ImportError:
    from enemy_cache import resolve_enemy_async

MODS_API = "http://111.170.14.106:18511/mods"
WFCD_WARFRAMES_URL = "https://cdn.jsdelivr.net/gh/WFCD/warframe-items@master/data/json/Warframes.json"
WFCD_WARFRAMES_API = "http://111.170.14.106:18511/warframes"

WARFRAME_TYPE_ZH = {
    "warframe": "战甲", "Warframe": "战甲", "Warframe Mod": "战甲MOD",
    "aura": "光环", "Aura": "光环",
}

GOAL_MAP = {
    "生存": ["health", "armor", "shield", "adaptation"],
    "强度": ["strength", "duration", "energy"],
    "效率": ["efficiency", "energy", "duration"],
    "范围": ["range", "duration"],
    "均衡": ["strength", "duration", "efficiency", "range"],
    "balanced": ["strength", "duration", "efficiency", "range"],
    "survival": ["health", "armor", "shield"],
    "strength": ["strength", "duration"],
    "efficiency": ["efficiency", "energy"],
    "range": ["range", "duration"],
    "duration": ["duration", "efficiency"],
}

GOAL_ZH = {
    "生存": "生存", "survival": "生存",
    "强度": "强度", "strength": "强度",
    "效率": "效率", "efficiency": "效率",
    "范围": "范围", "range": "范围",
    "duration": "持续时间",
    "均衡": "均衡", "balanced": "均衡",
}


class WarframeBuildMixin:
    """战甲配装 Mixin，与 BuildToolsMixin 风格一致"""

    def warframe_build_init(self):
        """初始化战甲配装状态，由主类 __init__ 调用"""
        self._wf_warframe_mod_cache = None
        self._wf_warframe_mod_cache_time = 0
        self._wf_warframe_cache = {}
        self._wf_warframe_cache_time = 0

    # ---------- 本地核心战甲 MOD ----------
    def _wf_load_warframe_mods_local(self) -> list[dict]:
        """加载本地核心战甲 MOD（现成中文名）"""
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wf_warframe_mods.json")
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            out = []
            for en, m in (data or {}).items():
                m = dict(m)
                m.setdefault("name", en)
                out.append(m)
            return out
        except Exception as e:
            logger.warning(f"[wfrag_tool] 本地战甲MOD加载失败: {e}")
            return []

    # ---------- /mods API 动态补齐 ----------
    def _wf_fetch_warframe_mods_sync(self) -> list[dict]:
        now = time.time()
        if self._wf_warframe_mod_cache and now - self._wf_warframe_mod_cache_time < 3600:
            return self._wf_warframe_mod_cache
        out = []
        try:
            req = urllib.request.Request(MODS_API, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                all_mods = json.loads(r.read().decode())
            for m in all_mods or []:
                t = str(m.get("type") or "").lower() + " " + str(m.get("category") or "").lower()
                if "warframe" in t:
                    out.append(m)
        except Exception as e:
            logger.warning(f"[wfrag_tool] /mods 战甲MOD拉取失败: {e}")
        self._wf_warframe_mod_cache = out
        self._wf_warframe_mod_cache_time = now
        return out

    async def _wf_get_warframe_mods(self) -> list[dict]:
        local = self._wf_load_warframe_mods_local()
        api = await asyncio.to_thread(self._wf_fetch_warframe_mods_sync)
        # 合并：本地优先，API 补齐（按名称去重）
        seen = {m.get("name") or m.get("en") for m in local if m.get("name") or m.get("en")}
        for m in api:
            mn = m.get("name") or m.get("zh_name") or ""
            if mn and mn not in seen:
                seen.add(mn)
                local.append(m)
        logger.info(f"[wfrag_tool] 战甲MOD: 本地{len(self._wf_load_warframe_mods_local())} + API补{max(0,len(local)-len(self._wf_load_warframe_mods_local()))} = {len(local)}")
        return local if local else api

    # ---------- 战甲面板 ----------
    def _wf_fetch_warframes_sync(self) -> dict:
        now = time.time()
        if self._wf_warframe_cache and now - self._wf_warframe_cache_time < 86400:
            return self._wf_warframe_cache
        out = {}
        # 优先用我们的 API（含中文名 + 黑话别名），失败回退 WFCD CDN
        sources = [WFCD_WARFRAMES_API, WFCD_WARFRAMES_URL]
        for url in sources:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read().decode())
                for wf in data or []:
                    if wf.get("name"):
                        key = wf["name"].lower()
                        out[key] = wf
                        # 额外索引：中文名 + 黑话别名（保证 _wf_find_warframe 能通过别名命中）
                if out:
                    logger.info(f"[wfrag_tool] 战甲面板来源: {url.split('/')[2]}")
                    break
            except Exception as e:
                logger.warning(f"[wfrag_tool] 战甲面板 {url} 拉取失败: {e}")
        self._wf_warframe_cache = out
        self._wf_warframe_cache_time = now
        return out

    def _wf_find_warframe(self, name: str) -> dict | None:
        q = name.strip().lower()
        cache = self._wf_fetch_warframes_sync()
        if q in cache:
            return cache[q]
        # 模糊 + 中文名 + 黑话别名尝试
        hits = [w for n, w in cache.items() if q in n or n in q]
        # 黑话别名匹配（做去空格/大小写归一化，兼容"悟空P" vs "悟空 p"）
        qn = q.replace(" ", "").replace("-", "")
        for w in cache.values():
            z = (w.get("zh_name") or "").lower().replace(" ", "")
            if qn == z:
                return w
            al = [str(a).lower().replace(" ", "") for a in (w.get("aliases") or [])]
            if qn in al:
                return w
        # 别名子串匹配
        for w in cache.values():
            al = [str(a).lower().replace(" ", "") for a in (w.get("aliases") or [])]
            if any(qn in a or a in qn for a in al):
                return w
        if len(hits) == 1:
            return hits[0]
        # 中文名映射兜底
        zh_map = {
            "咖喱棒": "Excalibur", "咖喱": "Excalibur", "圣剑": "Excalibur", "圣剑prime": "Excalibur Prime",
            "牛甲": "Rhino", "犀牛": "Rhino", "奶妈": "Trinity", "瓦喵": "Valkyr",
            "电男": "Volt", "磁妹": "Mag", "武僧": "Baruuk", "花甲": "Hildryn",
            "茶妹": "Protea", "蛆甲": "Nidus", "蝶妹": "Titania", "弓妹": "Ivara",
            "摸尸": "Nekros", "死灵": "Nekros", "哪吒": "Nezha", "悟空": "Wukong",
            "猴子": "Wukong", "阴阳": "Equinox", "儿子": "Atlas", "土甲": "Atlas",
            "玻璃甲": "Gara", "毒妈": "Saryn", "女枪": "Mesa", "诡计": "Loki",
            "洛基": "Loki", "冰男": "Frost", "冰甲": "Frost", "火鸡": "Ember",
            "火女": "Ember", "电鞭": "Khora", "猫甲": "Khora", "疯狗": "Valkyr",
            "夜灵": "Revenant", "夜灵甲": "Revenant", "小明": "Limbo", "limbo": "Limbo",
            "小明:": "Limbo", "xaku": "Xaku", "xaku甲": "Xaku", "紫妹": "Xaku",
            "驱魔": "Oberon", "奶爸": "Oberon", "主教": "Harrow", "神父": "Harrow",
        }
        if q in zh_map:
            q = zh_map[q].lower()
            if q in cache:
                return cache[q]
        return None

    def _wf_warframe_name_zh(self, name: str) -> str:
        """战甲中文名：优先 zh_dict 本地词库（Nyx），失败回退原文"""
        try:
            zh = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zh_dict.json")
            if os.path.exists(zh):
                with open(zh, encoding="utf-8") as f:
                    d = json.load(f)
                items = d if isinstance(d, list) else d.get("data", [])
                en = (name or "").strip()
                for it in items or []:
                    if isinstance(it, dict) and (it.get("en") or "").lower() == en.lower():
                        return it.get("zh") or name
                return name
        except Exception:
            pass
        return name

    # ---------- 选 MOD ----------
    def _wf_select_warframe_mods(self, mods: list[dict], goal: str, enemy_data: dict | None = None) -> list[dict]:
        targets = GOAL_MAP.get(goal, GOAL_MAP.get("balanced", ["strength", "duration", "efficiency", "range"]))
        enemy_focus = []
        if enemy_data:
            # 敌人弱点 -> 提示词加权（元素/机制相关词的 MOD）
            weak = " ".join(str(w) for w in (enemy_data.get("weaknesses") or []))
            if any(k in weak for k in ("腐蚀", "毒", "电", "corrosive", "toxin", "electric")):
                enemy_focus = ["health", "adaptation", "shield"]
            elif any(k in weak for k in ("辐射", "火", "爆炸", "radiation", "heat", "blast")):
                enemy_focus = ["strength", "duration"]
            elif enemy_data.get("mechanics"):
                enemy_focus = ["range", "duration", "efficiency"]

        def mod_score(m):
            stats = m.get("stats") or {}
            grp = str(m.get("group") or "").lower()
            s = 0
            for t in targets:
                if t == grp:
                    s += 3
            for t in enemy_focus:
                if t == grp:
                    s += 2
            s += sum(abs(v) for v in stats.values() if isinstance(v, (int, float))) * 0.01
            return s

        sorted_mods = sorted(mods, key=mod_score, reverse=True)
        out = []
        seen_grp = set()
        for m in sorted_mods:
            grp = str(m.get("group") or "").lower()
            # 每个 group 至多一个（光环可以不过滤）
            if grp and grp not in ("aura", "exilus") and grp in seen_grp:
                continue
            seen_grp.add(grp)
            out.append(m)
            if len(out) >= 8:
                break
        return out

    # ---------- LLM 工具 ----------
    @filter.llm_tool(name="wf_recommend_warframe_build")
    async def wf_recommend_warframe_build(self, event: AstrMessageEvent, **kwargs) -> str:
        """根据战甲名和流派推荐战甲 MOD 配装。

        用户问"XX战甲怎么配"、"配装 哪吒 打豺狼"、"战甲配卡"时调用。
        支持流派（生存/强度/效率/范围/均衡）与敌人感知（打谁自动调整）。

        Args:
            warframe(string): 战甲名（中英文皆可，如 "哪吒" "Nezha" "咖喱棒"）
            goal(string): 配装流派，可选 生存/强度/效率/范围/均衡（默认均衡）
            enemy(string): 攻击目标敌人名（可选，如 "豺狼" "虚空天使"）
            enemy_level(int): 敌人等级（可选）
        """
        name = str(kwargs.get("warframe", "")).strip()
        goal = str(kwargs.get("goal", "balanced") or "balanced").strip()
        enemy = str(kwargs.get("enemy", "")).strip()
        try:
            level = int(kwargs.get("enemy_level")) if kwargs.get("enemy_level") is not None else None
        except (TypeError, ValueError):
            level = None

        if not name:
            return json.dumps({"success": False, "message": "缺少参数 warframe（战甲名）"}, ensure_ascii=False)

        wf = self._wf_find_warframe(name)
        if wf:
            wf_zh = self._wf_warframe_name_zh(wf.get("name", name))
            panel = (
                f"  护甲: {wf.get('armor','?')} | 生命: {wf.get('health','?')} | "
                f"护盾: {wf.get('shield','?')} | 能量: {wf.get('energy','?')} | "
                f"冲刺: {wf.get('sprintSpeed','?')}"
            )
        else:
            wf_zh = self._wf_warframe_name_zh(name)
            panel = "  面板数据暂未收录，使用通用配装"

        mods = await self._wf_get_warframe_mods()
        if not mods:
            return json.dumps({"success": False, "message": "未找到战甲 MOD 数据，请检查 /mods API 与本地数据库"}, ensure_ascii=False)

        enemy_data = None
        enemy_label = enemy or ""
        if enemy:
            try:
                enemy_data = await resolve_enemy_async(enemy)
                if enemy_data:
                    enemy_label = enemy_data.get("name") or enemy
            except Exception as e:
                logger.warning(f"[wfrag_tool] 敌人解析失败: {e}")

        selected = self._wf_select_warframe_mods(mods, goal, enemy_data)
        if not selected:
            selected = mods[:8]

        goal_zh = GOAL_ZH.get(goal, goal)
        lines = [f"🛡 {wf_zh} 推荐配装（{goal_zh}）", panel, "", "【MOD 配置】"]
        for i, m in enumerate(selected, 1):
            mn = m.get("name") or m.get("zh_name") or m.get("en") or "?"
            desc = ", ".join(f"{k} {v:+.0%}" for k, v in (m.get("stats") or {}).items() if isinstance(v, (int, float)) and v)
            pol = m.get("polarity", "")
            lines.append(f"  {i}. {mn} — {desc} [drain:{m.get('drain',0)}] {pol}")
        lines.append(f"\n📊 共 {len(mods)} 个战甲 MOD 可用（本地+API动态补齐）")

        if enemy_data:
            lines.append(f"\n【对 {enemy_label} 调整】")
            if enemy_data.get("weaknesses"):
                lines.append("  敌人弱点：" + "、".join(str(w) for w in enemy_data["weaknesses"]))
            if enemy_data.get("mechanics"):
                lines.append("  敌人机制：" + "；".join(str(x) for x in enemy_data["mechanics"]))

        return "\n".join(lines)

    # ---------- 直接命令处理（#配甲） ----------
    async def wf_warframe_cmd_result(self, arg: str) -> str:
        """解析 #配甲 参数并返回结果（兼容任意前缀）"""
        parts = [p for p in str(arg or "").split() if p.strip()]
        if not parts:
            return ("战甲配装用法：\n"
                    "  配甲 哪吒             → 默认均衡配装\n"
                    "  配甲 哪吒 强度流       → 指定流派\n"
                    "  配甲 哪吒 打豺狼       → 针对敌人配装\n"
                    "流派：生存/强度/效率/范围/均衡")
        name = parts[0]
        rest = " ".join(parts[1:])
        goal = "balanced"
        enemy = ""
        for g in ("生存", "强度", "效率", "范围", "均衡", "survival", "strength", "efficiency", "range", "balanced", "duration"):
            if g in rest:
                goal = g
                rest = rest.replace(g, "", 1).strip()
                break
        if "打" in rest:
            enemy = rest.split("打", 1)[1].strip()
        elif rest.strip():
            enemy = rest.strip()
        return await self.wf_recommend_warframe_build(event=None, warframe=name, goal=goal, enemy=enemy)
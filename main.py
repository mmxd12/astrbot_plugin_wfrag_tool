"""AstrBot LLM 工具插件：Warframe 实时数据 + Wiki RAG

注册 7 个 llm_tool（function calling），让 LLM 在对话中主动调用：
  - wf_rag_search         检索 Warframe 中文 Wiki 知识库（wf-rag 服务 / 8765）
  - wf_market_price       Warframe Market 市价查询（wf-api / 3000，支持黑话）
  - wf_riven_price        紫卡（Riven）拍卖查询（wf-api /wmr，中英文武器名）
  - wf_lich_price         玄骸/姐妹（Kuva/Tenet）武器市场价（wf-api /wmw）
  - wf_world_state        世界状态查询（电波/突击/裂缝/奸商/钢铁之路/仲裁…）
  - wf_arbitration_essence 仲裁精华表（精华/小时、品质、节点）
  - wf_dict               词库/黑话解析（wf-api / 3000）

依赖两个本地服务（只读 HTTP，插件本身不缓存任何数据）：
  - wf-api  http://127.0.0.1:3000   (node wf-api，市价/世界状态/词库)
  - wf-rag  http://127.0.0.1:8765   (python wf-rag/server.py，Wiki 检索)

部署：
  本文件作为 main.py 放入 data/plugins/astrbot_plugin_wfrag_tool/，
  连同 metadata.yaml、_conf_schema.json 一起，重启 AstrBot 并启用插件。
  若 wf-api / wf-rag 未启动，工具会返回可读的错误提示，不影响其他功能。
"""
import asyncio
import json
import threading
import urllib.parse
import urllib.request

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
import sys
sys.path.insert(0, "/AstrBot/data/tools")
from riven_analyse import parse_ocr_text, analyse_riven, resolve_weapon

from astrbot.api.star import Context, Star, register

# 默认服务地址（可用 _conf_schema.json 里的配置覆盖）
WF_API = "http://127.0.0.1:3000"
WF_RAG = "http://127.0.0.1:8765"
TIMEOUT = 30

# 常见世界状态类型 -> 提示语（供 LLM 参考，不强制）
WS_TYPES = "电波|突击|裂缝|钢铁裂缝|九重天|奸商|达尔沃|小小黑|钢铁之路|执刑官|仲裁|仲裁精华(arb)|入侵|警报|双衍|科研|全局增益|赤毒|舰队|先遣舰|日历|促销|新闻|活动|集团任务|时间戳|地球|金星|火卫二|扎里曼|赏金|科维兽|1999赏金"


@register("astrbot_plugin_wfrag_tool", "小浅", "Warframe LLM 工具：Wiki RAG + 市价 + 紫卡(wmr) + 玄骸/姐妹(wmw) + 世界状态 + 仲裁精华 + 词库", "1.4.0")
class WFRagTool(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        cfg = config or {}
        self.api = (cfg.get("wf_api_url") or WF_API).rstrip("/")
        self.rag = (cfg.get("wf_rag_url") or WF_RAG).rstrip("/")
        self.timeout = int(cfg.get("timeout") or TIMEOUT)
        self._health = {}  # 后台自检结果: {"wf_api": bool, "wf_rag": bool}
        logger.info(f"[wfrag_tool] 就绪 | wf-api: {self.api} | wf-rag: {self.rag}")
        threading.Thread(target=self._startup_check, daemon=True).start()

    # ---------- 启动自检 ----------

    def _ping(self, url: str, timeout: int = 5) -> bool:
        """只探活：任意 200 即认为服务在线，不解析返回体（wf-api 根路由是 HTML）。"""
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": "wfrag-tool/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def _startup_check(self) -> None:
        """后台探活两个后端服务，把结果写进日志（离线时醒目提示）。"""
        self._health = {
            "wf_api": self._ping(self.api + "/"),
            "wf_rag": self._ping(self.rag + "/health"),
        }
        ok_api, ok_rag = self._health["wf_api"], self._health["wf_rag"]
        if ok_api and ok_rag:
            logger.info("[wfrag_tool] 启动自检通过：wf-api ✓ | wf-rag ✓")
            return
        if not ok_api:
            logger.warning("[wfrag_tool] ⚠ wf-api 未连接（市价/世界状态/词库工具将不可用），请先启动: cd wf-api && npm start")
        if not ok_rag:
            logger.warning("[wfrag_tool] ⚠ wf-rag 未连接（Wiki 检索工具将不可用），请先启动: cd wf-rag && python server.py")

    def _health_line(self) -> str:
        """/wfllm 帮助里展示的服务状态行。"""
        h = self._health
        if not h:
            return "服务自检中…（稍后再试 /wfllm）"
        mk = lambda ok: "✓ 在线" if ok else "✗ 离线"
        return f"wf-api: {mk(h.get('wf_api'))} | wf-rag: {mk(h.get('wf_rag'))}"

    # ---------- HTTP 基础 ----------

    def _get_json(self, url: str, timeout: int | None = None) -> dict:
        """同步 GET，返回 JSON；任何异常都转成可读的 dict 结果。"""
        t = timeout or self.timeout
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "wfrag-tool/1.0"})
            with urllib.request.urlopen(req, timeout=t) as r:
                return {"__ok": True, "__data": json.load(r)}
        except Exception as e:
            return {"__ok": False, "__err": f"{type(e).__name__}: {e}"}

    async def _get(self, url: str, timeout: int | None = None) -> dict:
        return await asyncio.to_thread(self._get_json, url, timeout)

    def _q(self, base: str, path: str, **params) -> str:
        url = base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    @staticmethod
    def _strip_big(d, drop=("icon", "thumb", "i18n", "image", "avatar", "subIcon")):
        """递归剔除图片/多语言等大字段，压缩返回体。"""
        if isinstance(d, dict):
            return {k: WFRagTool._strip_big(v) for k, v in d.items() if k not in drop}
        if isinstance(d, list):
            return [WFRagTool._strip_big(x) for x in d]
        return d

    @staticmethod
    def _trim(s: str, n: int = 3000) -> str:
        return s if len(s) <= n else s[:n] + f"\n...（已截断，共 {len(s)} 字符）"

    # ---------- 图片识别（紫卡截图 → 词条文本） ----------

    @staticmethod
    async def _collect_images(event: AstrMessageEvent) -> list[str]:
        """取出消息里的图片本地路径，含引用消息里的图片。"""
        from astrbot.api.message_components import Image, Reply

        comps = list(event.get_messages() or [])
        # 回复某条带图消息时，图片在 Reply.chain 里
        for c in list(comps):
            if isinstance(c, Reply) and c.chain:
                comps.extend(c.chain)

        paths = []
        for c in comps:
            if not isinstance(c, Image):
                continue
            try:
                paths.append(await c.convert_to_file_path())
            except Exception as e:
                logger.warning(f"[wfrag_tool] 图片转本地路径失败: {e}")
        return paths

    # 让视觉模型只吐结构化文本，点评交给主对话的 LLM
    _OCR_PROMPT = (
        "这是一张 Warframe 紫卡（Riven Mod）截图。请只读出卡面文字，按下面格式输出，"
        "不要解释、不要点评、不要加任何多余内容：\n"
        "第一行：武器名（卡面上武器名后面形如 Vexi-critadra 的连字符英文是紫卡随机后缀名，"
        "不是武器名，必须丢掉；若卡面能看到武器英文名则优先输出英文名）\n"
        "之后每行一条词条，格式为 符号+数值% 词条名，例如：\n"
        "Sobek\n"
        "+72% 电击伤害\n"
        "+68.5% 暴击几率\n"
        "-71.2% 冲击伤害\n"
        "注意保留正负号与小数，忽略段位/循环次数/极性等非词条信息。"
    )

    async def _ocr_riven(self, event: AstrMessageEvent, paths: list[str]) -> str:
        """用本地 PaddleOCR 读紫卡截图，返回词条文本（无需 LLM）。"""
        if not paths:
            raise RuntimeError("没有找到图片")
        try:
            from rapidocr_onnxruntime import RapidOCR
            engine = RapidOCR()
            result, elapse = engine(paths[0])
        except ImportError:
            raise RuntimeError("本地 OCR 引擎不可用，请安装 rapidocr-onnxruntime")
        except Exception as e:
            raise RuntimeError(f"OCR 识别失败: {e}")

        if not result:
            raise RuntimeError("OCR 未识别到任何文字")

        # 把所有识别到的文本按 Y 坐标排序后拼接
        items = [(box[0][1], text) for box, text, score in result if text.strip()]
        items.sort(key=lambda x: x[0])  # 按 Y 坐标从上到下排序
        lines = [text.strip() for _, text in items if text.strip()]

        # 过滤掉段位等级、极性、数字代码等非卡面词条内容
        import re
        filtered = []
        for line in lines:
            # 跳过纯数字/百分比/段位/极性/小字
            if re.match(r'^\d+[Vv]?$', line) or line in ('MOD', 'Riven', 'Mod', '裂罅'):
                continue
            if re.match(r'^[A-Za-z]+-[A-Za-z]+$', line):  # 随机后缀名如 Igni-visican
                continue
            if re.match(r'^[\d.]+[kKmM]?$', line):
                continue
            if '段位' in line or '循环' in line or '容量' in line:
                continue
            filtered.append(line)

        if not filtered:
            raise RuntimeError("OCR 未识别到有效词条")

        # 第一行是武器名（去掉随机后缀名）
        weapon_line = filtered[0]
        weapon_line = re.sub(r'\s*[A-Za-z]+-[A-Za-z]+\s*$', '', weapon_line).strip()
        lines_out = [weapon_line]

        # 剩下的行，把词条整理成标准格式
        for line in filtered[1:]:
            line = line.strip()
            if not line:
                continue
            # 处理卡面格式：+111.7%多重射击
            m = re.match(r'([+\-xX×])\s*([\d.]+)\s*%?\s*(.+)', line)
            if m:
                sign, val, name = m.group(1), m.group(2), m.group(3).strip()
                lines_out.append(f"{sign}{val}% {name}")
                continue
            # 名字在前：多重射击 +111.7%
            m = re.match(r'(.+?)\s*[+\-xX×]\s*([\d.]+)\s*%?', line)
            if m:
                name, val = m.group(1).strip(), m.group(2)
                sign = '+' if '+' in line else '-'
                lines_out.append(f"{sign}{val}% {name}")
                continue
            # 带 x 的负面：x0.57对Corpus的伤害
            m = re.match(r'[xX×]\s*([\d.]+)\s*(.+)?', line)
            if m:
                val = float(m.group(1))
                name = (m.group(2) or '').strip() or '伤害'
                pct = round((1 - val) * 100, 1)
                lines_out.append(f"-{pct}% {name}")
                continue
            lines_out.append(line)

        return "\n".join(lines_out)

    # ---------- 工具 1：RAG 检索 ----------

    @filter.llm_tool(name="wf_rag_search")
    async def wf_rag_search(self, event: AstrMessageEvent, **kwargs) -> str:
        """检索 Warframe 中文 Wiki 知识库（RAG）

        当用户问游戏机制、数值、公式类问题（如“电击异常几层”“护甲减伤怎么算”“紫卡怎么洗”）时调用。
        返回 wiki 权威片段与出处，回答时数值/机制以检索结果为准，不要凭记忆编造。

        Args:
            query(string): 问题或关键词，如 “电击的异常状态” “护甲减伤公式”
            top_k(int): 返回片段数，默认 4，最大 8

        返回:
            JSON: {success, context(文本), sources:[{title, section, url, score}]}
        """
        q = str(kwargs.get("query", "")).strip()
        if not q:
            return json.dumps({"success": False, "message": "缺少参数 query"}, ensure_ascii=False)
        try:
            k = max(1, min(int(kwargs.get("top_k", 4) or 4), 8))
        except (TypeError, ValueError):
            k = 4

        url = self._q(self.rag, "/check", q=q)
        ck = await self._get(url, timeout=20)
        if not ck["__ok"]:
            return json.dumps({"success": False, "message": f"wf-rag 服务不可用: {ck['__err']}（请确认 wf-rag/server.py 已启动）"}, ensure_ascii=False)
        if not ck["__data"].get("has_entity"):
            return json.dumps({"success": False, "message": f"「{q}」未命中 Wiki 术语，可能是闲聊或表述太泛。请明确到具体机制/物品名（如 电击、护甲减伤、裂罅）后再试"}, ensure_ascii=False)

        url = self._q(self.rag, "/context", q=q, k=k, max=4000)
        r = await self._get(url, timeout=20)
        if not r["__ok"]:
            return json.dumps({"success": False, "message": f"wf-rag 服务不可用: {r['__err']}（请确认 wf-rag/server.py 已启动）"}, ensure_ascii=False)
        d = r["__data"]
        if d.get("state") != "success":
            return json.dumps({"success": False, "message": d.get("msg", "检索失败")}, ensure_ascii=False)
        ctx = d.get("context") or ""
        srcs = [{k: s.get(k) for k in ("title", "section", "url", "score")} for s in (d.get("sources") or [])]
        if not ctx:
            return json.dumps({"success": False, "message": f"未检索到与「{q}」相关的资料，请换种说法或明确机制名"}, ensure_ascii=False)
        return json.dumps({"success": True, "context": self._trim(ctx, 4000), "sources": srcs}, ensure_ascii=False)

    # ---------- 工具 2：市价查询 ----------

    @filter.llm_tool(name="wf_market_price")
    async def wf_market_price(self, event: AstrMessageEvent, **kwargs) -> str:
        """查询 Warframe Market 物品价格（支持玩家黑话）

        用户问“XX多少钱”“XX值不值”“XX什么价”“现在XX的行情”时调用。
        物品名支持中文、英文、玩家黑话（如 奶妈P、福马、紫卡、高斯P、咖喱棒）。

        Args:
            item(string): 物品名，如 “奶妈P” “Trinity Prime” “福马” “金元”

        返回:
            JSON: {success, item, en, zh, statistics:{avg,min,max,median,volume}, top_sellers:[{name,price,qty,status}]}
        """
        item = str(kwargs.get("item", "")).strip()
        if not item:
            return json.dumps({"success": False, "message": "缺少参数 item"}, ensure_ascii=False)
        url = self.api + "/wm/" + urllib.parse.quote(item)
        r = await self._get(url)
        if not r["__ok"]:
            return json.dumps({"success": False, "message": f"wf-api 服务不可用: {r['__err']}"}, ensure_ascii=False)
        d = r["__data"]
        if isinstance(d, dict) and d.get("error"):
            return json.dumps({"success": False, "message": str(d["error"])}, ensure_ascii=False)
        word = d.get("word") or {}
        st = d.get("statistics") or {}
        raw = d.get("seller") or []
        # 有价格、按价格升序
        priced = [s for s in raw if s.get("platinum") is not None]
        priced.sort(key=lambda s: s["platinum"])
        online = []
        offline = []
        for s in priced:
            sts = (s.get("user") or {}).get("status", "")
            (offline if sts == "offline" else online).append(s)
        en_name = word.get("en") or d.get("en") or d.get("name") or ""
        zh_name = word.get("zh") or d.get("name") or ""
        STATUS_MAP = {"ingame": "游戏中", "online": "在线", "offline": "离线"}
        def slim(seller):
            u = seller.get("user") or {}
            name = u.get("ingameName", "")
            price = seller.get("platinum")
            sts = u.get("status", "")
            return {
                "name": name,
                "price": price,
                "qty": seller.get("quantity"),
                "status": STATUS_MAP.get(sts, sts),
                "buy_template": f"/w {name} Hi! I want to buy: {en_name} for {price} platinum." if price and name else "",
            }
        out = {
            "success": True,
            "item": d.get("name"),
            "en": word.get("en"),
            "zh": word.get("zh"),
            "statistics": {
                "avg_price": st.get("avg_price"), "min_price": st.get("min_price"),
                "max_price": st.get("max_price"), "median": st.get("median"),
                "volume": st.get("volume"), "wa_price": st.get("wa_price"),
            },
            "top_sellers": [slim(s) for s in online[:10]],
            "offline_reference": [slim(s) for s in offline[:5]],
        }
        # 在最前面插入一行人类可读的概要
        en = word.get("en") or ""
        zh = word.get("zh") or d.get("name") or ""
        av = st.get("avg_price")
        md = st.get("median")
        lo = st.get("min_price")
        hi = st.get("max_price")
        vo = st.get("volume")
        summary = f"📦 {zh}（{en}）"
        if av is not None:
            summary += "\n" + f"均价 {av} | 中位 {md} | 最低 {lo} | 最高 {hi} | 成交量 {vo}"
        out["summary"] = summary
        return json.dumps(out, ensure_ascii=False)

    # ---------- 工具 3：紫卡拍卖查询（wmr） ----------

    RIVEN_ATTR_ZH = {
        "damage": "基伤", "multishot": "多重", "critical_chance": "暴率",
        "critical_damage": "暴伤", "status_chance": "触发", "status_duration": "触发持续",
        "fire_rate": "射速", "magazine_capacity": "弹匣", "ammo_max": "备弹",
        "reload_speed": "换弹", "punch_through": "穿透", "zoom": "变焦",
        "heat_damage": "火焰", "cold_damage": "冰冻", "toxin_damage": "毒素",
        "electric_damage": "电击", "impact_damage": "冲击", "puncture_damage": "穿刺",
        "slash_damage": "切割", "damage_vs_grineer": "对G", "damage_vs_corpus": "对C",
        "damage_vs_infested": "对I", "projectile_speed": "弹速", "flight_speed": "飞行速度",
        "combo_duration": "连击持续", "attack_speed": "攻速", "range": "范围",
        "slide": "滑铲", "initial_combo": "初始连击", "negative_magazine_capacity": "弹匣减",
    }

    @filter.llm_tool(name="wf_riven_price")
    async def wf_riven_price(self, event: AstrMessageEvent, **kwargs) -> str:
        """查询 Warframe 紫卡（Riven Mod）拍卖行情（wmr 接口）

        用户问“XX武器的紫卡多少钱”“XX紫卡什么价”“wmr XX”“紫卡行情”时调用。
        支持中文/英文武器名（如 食人女魔、Ogris、诸葛连弩）。

        用户发紫卡截图求分析时，本工具应与 wf_riven_analyse **并发调用**，
        用挂单价给出市场对照，不要等分析结果出来再串行查。

        Args:
            item(string): 武器名，中英文皆可，如 “食人女魔” “Ogris”
            page(int): 可选，页数，默认 1，每页约 10 条

        返回:
            JSON: {success, name, total(挂单总数), word:{en,zh,type,disposition,reqMasteryRank},
                   sellers:[{price(直购), starting_price(起拍), attributes(属性), polarity, owner, status}]}
        """
        item = str(kwargs.get("item", "")).strip()
        if not item:
            return json.dumps({"success": False, "message": "缺少参数 item（武器名）"}, ensure_ascii=False)
        try:
            page = max(1, int(kwargs.get("page", 1) or 1))
        except (TypeError, ValueError):
            page = 1
        url = self.api + "/wmr/" + urllib.parse.quote(item) + f"?page={page}"
        r = await self._get(url)
        if not r["__ok"]:
            return json.dumps({"success": False, "message": f"wf-api 服务不可用: {r['__err']}"}, ensure_ascii=False)
        d = r["__data"]
        if isinstance(d, dict) and (d.get("error") or d.get("word") is None):
            return json.dumps({"success": False, "message": str(d.get("error") or f"未找到武器「{item}」的紫卡数据")}, ensure_ascii=False)
        word = d.get("word") or {}
        en_name = word.get("en") or d.get("name") or ""
        zh_name = word.get("zh") or d.get("name") or ""
        STATUS_MAP = {"ingame": "游戏中", "online": "在线", "offline": "离线"}
        STATUS_ICON = {"ingame": "🔴", "online": "🟢", "offline": "⚪"}
        raw = d.get("seller") or []
        # 有价格、按直购价升序（无直购价用起拍价）
        priced = [s for s in raw if s.get("buyout_price") is not None or s.get("starting_price") is not None]
        priced.sort(key=lambda s: s.get("buyout_price") or s.get("starting_price") or 999999)
        online = []
        offline = []
        for s in priced:
            sts = (s.get("owner") or {}).get("status", "")
            (offline if sts == "offline" else online).append(s)
        def slim(seller):
            ow = seller.get("owner") or {}
            name = ow.get("ingame_name", "")
            price = seller.get("buyout_price") or seller.get("starting_price")
            sts = ow.get("status", "")
            it = seller.get("item") or {}
            attrs = []
            for a in (it.get("attributes") or []):
                nm = self.RIVEN_ATTR_ZH.get(a.get("url_name"), a.get("url_name"))
                sign = "+" if a.get("positive") else "-"
                attrs.append(f"{sign}{nm}{a.get('value'):g}")
            return {
                "owner": name,
                "price": price,
                "attributes": attrs,
                "polarity": it.get("polarity"),
                "status": STATUS_MAP.get(sts, sts),
                "status_icon": STATUS_ICON.get(sts, "⚪"),
                "buy_template": f"/w {name} Hi! I want to buy: {en_name} Riven for {price} platinum, Are you still selling?" if price and name else "",
            }
        out = {
            "success": True,
            "name": d.get("name"),
            "total": d.get("total"),
            "word": {
                "en": word.get("en"), "zh": word.get("zh"),
                "type": word.get("rivenType") or word.get("type"),
                "disposition": word.get("disposition"),
                "reqMasteryRank": word.get("reqMasteryRank"),
            },
            "top_sellers": [slim(s) for s in online[:10]],
            "offline_reference": [slim(s) for s in offline[:5]],
        }
        st = d.get("statistics") or {}
        av = st.get("avg_price")
        md = st.get("median")
        lo = st.get("min_price")
        hi = st.get("max_price")
        vo = st.get("volume")
        summary = f"🔫 {zh_name}（{en_name}）"
        rtype = word.get("rivenType") or word.get("type") or ""
        disp = word.get("disposition") or ""
        total = d.get("total") or 0
        summary += "\n" + f"紫卡行情 | 类型：{rtype} | 倾向：{disp} | 挂单总数：{total}"
        if av is not None:
            summary += "\n" + f"均价 {av} | 中位 {md} | 最低 {lo} | 最高 {hi} | 成交量 {vo}"
        out["summary"] = summary
        return self._trim(json.dumps(out, ensure_ascii=False), 3500)

    # ---------- 工具 4：玄骸/姐妹武器市场价（wmw） ----------

    @filter.llm_tool(name="wf_lich_price")
    async def wf_lich_price(self, event: AstrMessageEvent, **kwargs) -> str:
        """查询玄骸/姐妹武器（Kuva / Tenet）市场价（wmw 接口，支持多属性筛选）

        用户问“赤毒XX多少钱”“信条XX什么价”“wmw XX”“玄骸武器行情”时调用。
        支持中文/英文武器名（如 食人女魔、Kuva Ogris、信条·循环离子枪）。
        支持按元素/百分比/最高价筛选，如 “wmw 食人女魔 毒 60%” “赤毒 沙皇 火 50% 200p内”。

        Args:
            item(string): 武器名，中英文皆可，如 “食人女魔” “Kuva Ogris”
            element(string): 可选，筛选元素（毒/毒素/toxin、火/heat、冰/cold、电/electricity、磁/magnetic、辐射/radiation、冲击/impact…）
            percent(int): 可选，最低元素百分比（如 60 或 "60%"），玄骸元素百分比范围 25~60
            max_price(int): 可选，最高价格（如 200 或 "200p"）
            page(int): 可选，起始页数，默认 1

        返回:
            JSON: {success, name, total(筛选后数量), word:{en,zh,type,reqMasteryRank},
                   summary(概要行，含筛选条件),
                   top_sellers:[{owner, price, item(元素/伤害%), status, status_icon, buy_template}],
                   offline_reference:[...]}
        """
        item = str(kwargs.get("item", "")).strip()
        if not item:
            return json.dumps({"success": False, "message": "缺少参数 item（武器名）"}, ensure_ascii=False)
        try:
            page = max(1, int(kwargs.get("page", 1) or 1))
        except (TypeError, ValueError):
            page = 1
        # ---- 多属性筛选参数 ----
        element = str(kwargs.get("element", "") or "").strip()
        percent = kwargs.get("percent")
        if percent is not None:
            try:
                percent = int(str(percent).replace("%", "").strip())
            except (TypeError, ValueError):
                percent = None
        max_price = kwargs.get("max_price")
        if max_price is not None:
            try:
                max_price = int(str(max_price).replace("p", "").replace("白金", "").strip())
            except (TypeError, ValueError):
                max_price = None
        ELEMENT_ALIAS = {
            "toxin": "toxin", "毒": "toxin", "毒素": "toxin", "毒元素": "toxin",
            "heat": "heat", "火": "heat", "火焰": "heat", "火元素": "heat",
            "cold": "cold", "冰": "cold", "冰冻": "cold", "冰元素": "cold", "cryo": "cold",
            "electricity": "electricity", "电": "electricity", "电击": "electricity", "电元素": "electricity", "electric": "electricity",
            "magnetic": "magnetic", "磁": "magnetic", "磁性": "magnetic", "磁力": "magnetic", "磁元素": "magnetic",
            "radiation": "radiation", "辐射": "radiation", "放射": "radiation", "辐射元素": "radiation",
            "impact": "impact", "冲击": "impact", "冲击元素": "impact",
            "viral": "viral", "病毒": "viral", "corrosive": "corrosive", "腐蚀": "corrosive",
            "blast": "blast", "爆炸": "blast", "puncture": "puncture", "穿刺": "puncture",
            "slash": "slash", "切割": "slash", "gas": "gas", "毒气": "gas",
        }
        element_filter = None
        if element:
            element_filter = ELEMENT_ALIAS.get(element.lower(), element.lower())

        # ---- 拉取数据（需要筛选时翻页） ----
        async def _fetch_one(pg):
            url = self.api + "/wmw/" + urllib.parse.quote(item) + f"?page={pg}"
            return await self._get(url)

        first = await _fetch_one(page)
        if not first["__ok"]:
            return json.dumps({"success": False, "message": f"wf-api 服务不可用: {first['__err']}"}, ensure_ascii=False)
        d = first["__data"]
        if isinstance(d, dict) and (d.get("error") or d.get("word") is None):
            return json.dumps({"success": False, "message": str(d.get("error") or f"未找到武器「{item}」的玄骸/姐妹数据")}, ensure_ascii=False)
        word = d.get("word") or {}
        en_name = word.get("en") or d.get("name") or ""
        zh_name = word.get("zh") or d.get("name") or ""
        raw = list(d.get("seller") or [])
        need_filter = element_filter is not None or percent is not None or max_price is not None
        if need_filter:
            for pg in range(page + 1, page + 6):
                r = await _fetch_one(pg)
                if not r["__ok"]:
                    break
                dd = r["__data"]
                if not isinstance(dd, dict) or dd.get("seller") is None:
                    break
                sels = dd.get("seller") or []
                raw.extend(sels)
                if len(sels) < 10:
                    break
        # ---- 条件筛选 ----
        if need_filter:
            filtered = []
            for s in raw:
                it = s.get("item") or {}
                price = s.get("buyout_price") or s.get("starting_price")
                if element_filter is not None and str(it.get("element") or "").lower() != element_filter:
                    continue
                if percent is not None:
                    dmg = it.get("damage")
                    if dmg is None or dmg < percent:
                        continue
                if max_price is not None and price is not None and price > max_price:
                    continue
                filtered.append(s)
            raw = filtered

        STATUS_MAP = {"ingame": "游戏中", "online": "在线", "offline": "离线"}
        STATUS_ICON = {"ingame": "🔴", "online": "🟢", "offline": "⚪"}
        priced = [s for s in raw if s.get("buyout_price") is not None or s.get("starting_price") is not None]
        priced.sort(key=lambda s: s.get("buyout_price") or s.get("starting_price") or 999999)
        online = []
        offline = []
        for s in priced:
            sts = (s.get("owner") or {}).get("status", "")
            (offline if sts == "offline" else online).append(s)
        def slim(seller):
            ow = seller.get("owner") or {}
            name = ow.get("ingame_name", "")
            price = seller.get("buyout_price") or seller.get("starting_price")
            sts = ow.get("status", "")
            it = seller.get("item") or {}
            it_slim = {k: v for k, v in it.items()
                       if k in ("element", "percent", "damage", "multishot",
                                "critical_chance", "status_chance", "fire_rate",
                                "magazine_size", "reload_speed") and v is not None}
            return {
                "owner": name,
                "price": price,
                "item": it_slim,
                "status": STATUS_MAP.get(sts, sts),
                "status_icon": STATUS_ICON.get(sts, "⚪"),
                "buy_template": f"/w{name} Hi! I want to buy: {en_name} Weapon for {price} platinum, Are you still selling?" if price and name else "",
            }
        out = {
            "success": True,
            "name": d.get("name"),
            "total": len(priced),
            "word": {
                "en": word.get("en"), "zh": word.get("zh"),
                "type": word.get("type"),
                "reqMasteryRank": word.get("reqMasteryRank"),
            },
            "top_sellers": [slim(s) for s in online[:10]],
            "offline_reference": [slim(s) for s in offline[:5]],
        }
        rtype = word.get("type") or ""
        cond = []
        if element_filter:
            cond.append(f"元素:{element_filter}")
        if percent is not None:
            cond.append(f"≥{percent}%")
        if max_price is not None:
            cond.append(f"≤{max_price}p")
        cond_txt = ("(" + " ".join(cond) + ") ") if cond else ""
        summary = f"🔫 {zh_name}（{en_name}）"
        summary += "\n" + f"玄骸武器行情{cond_txt}匹配 {len(priced)} 条"
        out["summary"] = summary
        return self._trim(json.dumps(out, ensure_ascii=False), 3500)
    @filter.llm_tool(name="wf_world_state")
    async def wf_world_state(self, event: AstrMessageEvent, **kwargs) -> str:
        """查询 Warframe 当前世界状态（实时）

        用户问“现在有什么任务/活动”“电波本周任务”“奸商来了吗”“突击是什么”“钢铁之路轮换”等时调用。

        Args:
            type(string): 状态类型，支持中文/英文。常用：
                电波(nightwave)、突击(sortie)、裂缝(fissures)、钢铁裂缝(steelFissures)、
                九重天(railjack)、奸商(voidTrader)、达尔沃(dailyDeals)、小小黑(persistentEnemies)、
                钢铁之路(steelPath)、执刑官(archonHunt)、仲裁(arbitration)、
                入侵(invasions)、警报(alerts)、双衍(duviriCycle)、科研(archimedeas)、
                全局增益(globalUpgrades)、赤毒(kuva)、舰队(constructionProgress)、
                先遣舰(sentientOutposts)、日历(calendar)、促销(flashSales)、
                新闻(news)、活动(events)、集团任务(syndicateMissions)、时间戳(timestamp)、
                地球/金星/火卫二/扎里曼 昼夜(earthCycle/vallisCycle/cambionCycle/zarimanCycle)、
                科维兽赏金/扎里曼赏金(Cavia)、1999赏金/霍瓦尼亚赏金(Hex)、
                地球赏金(Ostrons)、金星赏金(Solaris)、火卫二赏金(EntratiSyndicate)

        返回:
            JSON: 该类型的当前状态数据（已剔除图片等大字段）
        """
        t = str(kwargs.get("type", "")).strip()
        if not t:
            return json.dumps({"success": False, "message": f"缺少参数 type，可选: {WS_TYPES}"}, ensure_ascii=False)
        url = self.api + "/wf/" + urllib.parse.quote(t)
        r = await self._get(url)
        if not r["__ok"]:
            return json.dumps({"success": False, "message": f"wf-api 服务不可用: {r['__err']}"}, ensure_ascii=False)
        d = r["__data"]
        if isinstance(d, dict) and d.get("error"):
            return json.dumps({"success": False, "message": str(d["error"])}, ensure_ascii=False)
        d = self._strip_big(d)
        if isinstance(d, list) and len(d) > 10:
            d = d[:10] + [{"...": f"还有 {len(d) - 10} 项已省略"}]
        elif isinstance(d, dict):
            for k, v in list(d.items()):
                if isinstance(v, list) and len(v) > 10:
                    d[k] = v[:10] + [{"...": f"还有 {len(v) - 10} 项已省略"}]
        return self._trim(json.dumps(d, ensure_ascii=False), 3500)

    # ---------- 工具 4：仲裁精华 ----------

    @filter.llm_tool(name="wf_arbitration_essence")
    async def wf_arbitration_essence(self, event: AstrMessageEvent, **kwargs) -> str:
        """查询仲裁精华表：每个仲裁任务的精华/小时、品质、节点

        用户问“仲裁精华”“仲裁表”“仲裁奖励”“仲裁每小时多少精华”“仲裁哪个节点精华多”等时调用。

        Args:
            days(int): 可选，查询天数，默认7，最多30

        返回:
            JSON: {success, data:[{node, missionType, essence, quality, enemy, eta}]}
        """
        days = int(kwargs.get("days", 7)) if kwargs.get("days") is not None else 7
        days = max(1, min(days, 30))
        url = self.api + "/arb/" + str(days)
        r = await self._get(url)
        if not r["__ok"]:
            return json.dumps({"success": False, "message": f"wf-api 服务不可用: {r['__err']}"}, ensure_ascii=False)
        d = r["__data"]
        if isinstance(d, dict) and d.get("error"):
            return json.dumps({"success": False, "message": str(d["error"])}, ensure_ascii=False)
        if not isinstance(d.get("data"), list):
            return json.dumps({"success": False, "message": "仲裁精华数据暂不可用"}, ensure_ascii=False)
        items = d["data"]
        # 精华品质映射
        quality_map = {"S": "S级", "B": "B级", "C": "C级", "D": "D级"}
        out = []
        for item in items:
            q = item.get("quality", "N/A")
            out.append({
                "node": item.get("node"),
                "missionType": item.get("missionType"),
                "enemy": item.get("enemy"),
                "essence": item.get("essence"),
                "quality": quality_map.get(q, q),
                "eta": item.get("eta"),
            })
        return json.dumps({"success": True, "data": out}, ensure_ascii=False)

    
    # ---------- 工具 5.5：紫卡分析（riven-analyse） ----------

    @filter.llm_tool(name="wf_riven_analyse")
    async def wf_riven_analyse(self, event: AstrMessageEvent, **kwargs) -> str:
        """分析紫卡（Riven）品质

        当用户展示紫卡截图或输入词条数值要求分析紫卡品质时使用。
        根据词条数值和紫卡倾向计算理论区间和偏差百分比，帮助判断紫卡好坏。

        OCR 识别紫卡截图时：**武器英文名比中文名可靠**，若卡面同时可见英文，
        优先把英文名填进 weapon_name。注意卡面上形如 "Vexi-critadra"
        的连字符英文是紫卡随机后缀名，不是武器名，不要填。

        【调用方式】本工具与 wf_riven_price 应**同时并发调用**（两者互不依赖，
        并发后总延迟等于一次调用）。不要串行，也不要为了确认公式去读源码——
        计算已在本工具内完成。

        【回复要求】拿到结果后一次性输出三段，不要只报数值：
          1. 数值偏差：各词条实际值 vs 理论区间与偏差百分比（用 summary 即可）
          2. 词条组合评价：这套正面词条对该武器的实战价值、负面词条选得好不好、
             是否缺核心词条（如喷子缺多重射击）、适合什么流派（触发流/暴击流）。
             这部分靠你自己的游戏理解判断，不需要额外调用工具。
          3. 市场对照：用 wf_riven_price 的挂单价区间给出估价，并挑出词条方向
             相近的挂单做对比，最后给自用/出售的建议。
        若卡面数值明显是未满级状态，要提醒用户满级后偏差才准。

        Args:
            weapon_name(string): 武器名，中英文皆可，如 "食人女魔" "Ogris"。中文有错字也会自动纠正
            stats_text(string): 词条文本，如 "暴击几率 +119.2% 暴击伤害 +185.6% 触发几率 -7.6%"

        返回:
            JSON: {success, summary(分析结果), weapon_name, weapon_en, riven_type, omega, dot,
                   weapon_match(纠错信息，含 ambiguous 时说明武器名有歧义需向用户确认),
                   attrs:[{name,value,positive,low,high,mid,diff}]}
        """
        weapon_name = str(kwargs.get("weapon_name", "")).strip()
        stats_text = str(kwargs.get("stats_text", "")).strip()

        # 没传文字词条时，尝试从消息图片中 OCR 识别
        if not stats_text:
            try:
                paths = await self._collect_images(event)
                if paths:
                    stats_text = await self._ocr_riven(event, paths)
            except Exception as e:
                logger.warning(f"[wfrag_tool] OCR 识别失败: {e}")

        if not stats_text:
            return json.dumps({"success": False, "message": "缺少参数 stats_text（词条文本）"}, ensure_ascii=False)

        parsed = parse_ocr_text(stats_text)
        if weapon_name:
            # 显式给的武器名也过一遍武器表：OCR/用户输入的中文可能有错字
            hit = resolve_weapon(weapon_name)
            if hit:
                parsed["weapon_name"] = hit["zh"]
                parsed["weapon_en"] = hit["en"]
                parsed["riven_type"] = hit["rivenType"]
                parsed["weapon_match"] = {
                    "input": weapon_name, "by": hit["matched_by"], "score": hit["score"],
                }
                if hit.get("ambiguous"):
                    parsed["weapon_match"]["ambiguous"] = hit["ambiguous"]
            else:
                parsed["weapon_name"] = weapon_name

        if not parsed["attrs"]:
            return json.dumps({"success": False, "message": "未识别到词条数据，请检查格式（如：暴击几率 +119.2%）"}, ensure_ascii=False)

        try:
            result = analyse_riven(
                weapon_name=parsed["weapon_name"],
                attrs=parsed["attrs"],
                riven_type=parsed.get("riven_type"),
            )
            result["success"] = True
            if parsed.get("weapon_en"):
                result["weapon_en"] = parsed["weapon_en"]
            if parsed.get("weapon_match"):
                result["weapon_match"] = parsed["weapon_match"]
            return self._trim(json.dumps(result, ensure_ascii=False), 3500)
        except Exception as e:
            return json.dumps({"success": False, "message": f"分析失败: {type(e).__name__}: {e}"}, ensure_ascii=False)

# ---------- 工具 5：词库/黑话 ----------

    @filter.llm_tool(name="wf_dict")
    async def wf_dict(self, event: AstrMessageEvent, **kwargs) -> str:
        """查询 Warframe 词库：黑话/别名解析为正式名

        当不确定物品/战甲的正式英文名，或用户说了黑话想确认对应物品时调用（如 咖喱棒、奶妈P、三傻）。

        Args:
            keyword(string): 中文或英文关键词，如 “奶妈P” “咖喱棒” “三傻” “Teralyst”

        返回:
            JSON: {success, hits:[{key, en, zh, acc, ducats, tags}]}，第一条通常是最佳匹配
        """
        kw = str(kwargs.get("keyword", "")).strip()
        if not kw:
            return json.dumps({"success": False, "message": "缺少参数 keyword"}, ensure_ascii=False)
        url = self.api + "/dict/" + urllib.parse.quote(kw)
        r = await self._get(url)
        if not r["__ok"]:
            return json.dumps({"success": False, "message": f"wf-api 服务不可用: {r['__err']}"}, ensure_ascii=False)
        d = r["__data"]
        if isinstance(d, list) and d:
            hits = [{
                "key": it.get("key"),
                "en": it.get("en"),
                "zh": it.get("zh"),
                "acc": it.get("acc"),
                "ducats": it.get("ducats"),
                "tags": it.get("tags"),
                "alias": it.get("alias"),
            } for it in d[:6]]
            return json.dumps({"success": True, "hits": hits}, ensure_ascii=False)

        # Fallback: /dict 没结果，用 /wmr 查武器名翻译
        try:
            url2 = self.api + "/wmr/" + urllib.parse.quote(kw)
            r2 = await self._get(url2)
            if r2["__ok"]:
                wd = r2["__data"]
                word = wd.get("word") or {}
                en = word.get("slug", "")
                zh = word.get("i18n", {}).get("zh-hans", {}).get("name", kw)
                rtype = word.get("rivenType", word.get("type", "?"))
                disp = word.get("disposition", "?")
                hits = [{"key": kw, "en": en, "zh": zh, "tags": [rtype], "acc": disp, "ducats": None, "alias": None}]
                return json.dumps({"success": True, "hits": hits}, ensure_ascii=False)
        except Exception:
            pass

        return json.dumps({"success": False, "message": f"词库未找到「{kw}」，/dict 和 /wmr 均无结果"}, ensure_ascii=False)
        hits = [{  # unreachable but keeps syntax valid
            "key": it.get("key"),
            "en": it.get("en"),
            "zh": it.get("zh"),
            "acc": it.get("acc"),
            "ducats": it.get("ducats"),
            "tags": it.get("tags"),
            "alias": it.get("alias"),
        } for it in d[:6]]
        return json.dumps({"success": True, "hits": hits}, ensure_ascii=False)

    # ---------- 测试命令 ----------

    def _pretty(self, tool: str, text: str) -> str:
        """把工具返回的 JSON 转成人类可读文本（仅测试命令展示用）。"""
        try:
            d = json.loads(text)
        except Exception:
            return text
        if isinstance(d, dict) and d.get("success") is False:
            return f"\u26a0 {d.get('message', '查询失败')}"
        try:
            if tool in ("price", "wm", "p"):
                st = d.get("statistics") or {}
                lines = [
                    f"\U0001f4e6 {d.get('zh') or d.get('item')}（{d.get('en') or ''}）",
                    f"  均价 {st.get('avg_price')} | 中位 {st.get('median')} | "
                    f"最低 {st.get('min_price')} | 最高 {st.get('max_price')} | "
                    f"成交量 {st.get('volume')}",
                ]
                for s in (d.get("top_sellers") or [])[:3]:
                    if s.get("name"):
                        lines.append(
                            f"  卖家 {s['name']}: {s.get('price')}p × {s.get('qty')}"
                            f"（{s.get('status')}）")
                return "\n".join(lines)
            if tool in ("ws", "wf", "world", "w"):
                return self._ws_pretty(d)
            if tool in ("arb", "arbitration", "essence", "精华"):
                return self._arb_pretty(d)
            if tool in ("dict", "d"):
                lines = []
                for h in (d.get("hits") or [])[:6]:
                    lines.append(
                        f"  {h.get('key') or h.get('zh')} → {h.get('en')}"
                        f"{'（' + str(h.get('zh')) + '）' if h.get('zh') and h.get('key') else ''}"
                        f"{' | 紫卡价 ' + str(h.get('ducats')) if h.get('ducats') else ''}")
                return "\n".join(lines) or "（无结果）"
            if tool in ("rag", "search", "r"):
                return (d.get("context") or "")[:1500] + (
                    "\n\n来源: " + ", ".join(
                        s.get("title") for s in (d.get("sources") or [])[:3]))
        except Exception as e:
            return f"（格式化失败: {e}）\n{text[:800]}"
        return text[:1500]

    def _ws_pretty(self, d) -> str:
        """世界状态人类可读格式化（测试命令展示用）。"""
        try:
            if isinstance(d, dict) and "activeChallenges" in d:      # 电波
                lines = [f"🎯 电波第 {d.get('season')} 季，剩余 {d.get('eta') or '—'}"]
                for c in (d.get("activeChallenges") or [])[:8]:
                    lines.append(
                        f"  {'[周]' if not c.get('isDaily') else '[日]'}"
                        f"{c.get('title')}（{c.get('reputation')}声望）"
                        f"\n    {c.get('desc')} | 剩 {c.get('eta')}")
                return "\n".join(lines)
            if isinstance(d, dict) and "variants" in d:              # 突击
                lines = [f"⚔ 今日突击（奖励: {d.get('rewardPool')}）"]
                for v in (d.get("variants") or [])[:3]:
                    lines.append(
                        f"  {v.get('missionType')} | {v.get('node')}"
                        f"\n    修正: {v.get('modifier')} —— {v.get('modifierDescription')}")
                return "\n".join(lines)
            if isinstance(d, dict) and "currentReward" in d:          # 钢铁之路
                r = d.get("currentReward") or {}
                lines = [f"🛡 钢铁之路: 当前奖励 {r.get('name')}（{r.get('cost')} 声望），剩余 {d.get('remaining')}"]
                rot = []
                for i in (d.get("rotation") or [])[:6]:
                    rot.append(f"{i.get('name')}({i.get('cost')})")
                lines.append("  轮换: " + " | ".join(rot))
                return "\n".join(lines)
            if isinstance(d, dict) and "character" in d:              # 奸商
                inv = d.get("inventory") or []
                lines = [f"🧙 {d.get('character')} 在 {d.get('location')}"]
                if inv:
                    for it in inv[:8]:
                        lines.append(f"  {it.get('item')} — {it.get('ducats')} 杜卡 + {it.get('credits')} 现金")
                    if len(inv) > 8:
                        lines.append(f"  ...另有 {len(inv)-8} 项")
                else:
                    lines.append("  （本次清单尚未公布）")
                return "\n".join(lines)
            if isinstance(d, list) and d and "mission" in d[0]:       # 警报
                lines = [f"🚨 警报 {len(d)} 条"]
                for a in (d or [])[:6]:
                    m = a.get("mission") or {}
                    rw = m.get("reward") or {}
                    reward_txt = ""
                    ci = rw.get("countedItems") or []
                    if ci:
                        reward_txt = " | ".join(f"{x.get('count')}×{x.get('type')}" for x in ci[:3])
                    elif rw.get("credits"):
                        reward_txt = f"{rw.get('credits')} 现金"
                    lines.append(
                        f"  {m.get('type')} @ {m.get('node')}"
                        f"{' | 奖励: ' + reward_txt if reward_txt else ''}"
                        f" | 敌人 {m.get('minEnemyLevel')}-{m.get('maxEnemyLevel')}级")
                return "\n".join(lines)
            if isinstance(d, list) and d and "tier" in d[0]:          # 裂缝
                lines = [f"🌀 虚空裂缝 {len(d)} 条"]
                for f in (d or [])[:8]:
                    lines.append(
                        f"  {f.get('tier')} | {f.get('missionType')} @ {f.get('node')}"
                        f"{'（钢铁）' if f.get('isHard') else ''}"
                        f" | 剩 {(f.get('expiry') or '')[:16].replace('T', ' ')}")
                return "\n".join(lines)
            if isinstance(d, list) and d and "attacker" in d[0]:      # 入侵
                lines = [f"🪖 入侵 {len(d)} 条"]
                for inv in (d or [])[:6]:
                    def _rw(side):
                        rw = (side.get("reward") or {})
                        ci = rw.get("countedItems") or []
                        return " | ".join(f"{x.get('count')}×{x.get('type')}" for x in ci[:2]) or f"{rw.get('credits')}现金"
                    lines.append(
                        f"  {inv.get('node')}: {inv.get('attacker', {}).get('factionKey')}"
                        f"[{_rw(inv.get('attacker') or {})}] vs "
                        f"{inv.get('defender', {}).get('factionKey')}"
                        f"[{_rw(inv.get('defender') or {})}]")
                return "\n".join(lines)
        except Exception as e:
            return f"（世界状态格式化失败: {e}）"
        # 兜底: 未知结构, 输出摘要
        if isinstance(d, list):
            return f"共 {len(d)} 条:\n" + "\n".join(
                json.dumps(x, ensure_ascii=False)[:300] for x in d[:3])
        return json.dumps(d, ensure_ascii=False, indent=1)[:1500]

    def _arb_pretty(self, d) -> str:
        """仲裁精华人类可读格式化。"""
        items = d.get("data") or []
        if not items:
            return "暂无仲裁精华数据"
        lines = ["📋 仲裁精华表（精华/小时）", "─" * 40]
        for item in items[:15]:
            node = item.get("node", "?")
            ess = item.get("essence", "?")
            q = item.get("quality", "")
            mt = item.get("missionType", "?")
            en = item.get("enemy", "?")
            eta = item.get("eta", "?")
            lines.append(f"  {node}")
            lines.append(f"    {mt} vs {en} | {ess}精华/小时 ({q}) | {eta}")
        if len(items) > 15:
            lines.append(f"  ...还有 {len(items)-15} 条")
        return "\n".join(lines)

    @filter.command("wfllm", alias={"wfragtool"})
    async def test_tool(self, event: AstrMessageEvent):
        """测试 llm_tool：/wfllm <rag|price|ws|dict> <参数>"""
        # 优先用 AstrBot 解析好的命令参数（不同版本 message_str 可能带/不带斜杠）
        msg = ""
        try:
            arg = event.get_command_arg()
            if arg is not None and getattr(arg, "arg_str", None):
                msg = str(arg.arg_str).strip()
        except Exception:
            msg = ""
        if not msg:
            msg = (event.message_str or "").strip()
            for p in ("/wfllm", "#wfllm", "/wfragtool", "#wfragtool",
                      "wfragtool", "wfllm"):
                if msg == p:
                    msg = ""
                    break
                if msg.startswith(p + " "):
                    msg = msg[len(p):].strip()
                    break
        parts = msg.split(maxsplit=1)
        if not parts:
            yield event.plain_result(
                "Warframe LLM 工具插件 v1.4.0\n"
                f"服务状态：{self._health_line()}\n"
                "已注册 7 个 llm_tool：\n"
                "  wf_rag_search(query, top_k)       - Wiki 知识库检索\n"
                "  wf_market_price(item)             - 市价查询（支持黑话）\n"
                "  wf_riven_price(item, page)        - 紫卡拍卖查询（wmr，中英文武器名）\n"
                "  wf_lich_price(item, page)         - 玄骸/姐妹武器市场价（wmw）\n"
                "  wf_world_state(type)              - 世界状态（电波/突击/裂缝/钢裂/九重天/奸商/赏金…）\n"
                "  wf_arbitration_essence(days)      - 仲裁精华表（精华/小时、品质）\n"
                "  wf_riven_analyse(weapon_name, stats_text) - 紫卡分析（词条数值+倾向计算）\n  wf_dict(keyword)                  - 黑话/词库解析\n\n"
                "测试：/wfllm rag 电击异常 | price 奶妈P | riven 食人女魔 | lich 食人女魔 | ws 电波 | arb | dict 三傻"
            )
            return
        tool, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
        try:
            if tool in ("rag", "search", "r"):
                res = await self.wf_rag_search(event, query=arg)
            elif tool in ("price", "wm", "p"):
                res = await self.wf_market_price(event, item=arg)
            elif tool in ("riven", "r"):
                res = await self.wf_riven_price(event, item=arg)
            elif tool in ("lich", "l"):
                res = await self.wf_lich_price(event, item=arg)
            elif tool in ("ws", "wf", "world", "w"):
                res = await self.wf_world_state(event, type=arg)
            elif tool in ("arb", "arbitration", "essence", "精华"):
                days = int(arg) if arg.isdigit() else 7
                res = await self.wf_arbitration_essence(event, days=days)
            elif tool in ("riven", "ra", "analyse"):
                # 支持 /wfllm analyse [武器名] 直接带图：武器名可省略（OCR 自动读卡面）
                paths = await self._collect_images(event)
                weapon_arg = arg.split()[0] if arg.split() else ""
                if paths:
                    ocr_text = await self._ocr_riven(event, paths)
                    res = await self.wf_riven_analyse(
                        event, weapon_name=weapon_arg or "", stats_text=ocr_text,
                    )
                else:
                    res = await self.wf_riven_analyse(
                        event, weapon_name=weapon_arg, stats_text=arg,
                    )
            elif tool in ("dict", "d"):
                res = await self.wf_dict(event, keyword=arg)
            else:
                yield event.plain_result(f"未知工具: {tool}，可用 rag|price|riven|lich|ws|arb|dict")
                return
            yield event.plain_result(self._pretty(tool, res))
        except Exception as e:
            logger.error(f"[wfrag_tool] 测试异常: {e}")
            yield event.plain_result(f"异常: {type(e).__name__}: {e}")

    async def terminate(self) -> None:
        logger.info("[wfrag_tool] 已卸载")

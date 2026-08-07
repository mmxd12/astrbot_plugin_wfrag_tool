"""AstrBot LLM 工具插件：Warframe 实时数据 + Wiki RAG

注册 4 个 llm_tool（function calling），让 LLM 在对话中主动调用：
  - wf_rag_search   检索 Warframe 中文 Wiki 知识库（wf-rag 服务 / 8765）
  - wf_market_price Warframe Market 市价查询（wf-api / 3000，支持黑话）
  - wf_world_state  世界状态查询（电波/突击/裂缝/奸商/钢铁之路…）
  - wf_dict         词库/黑话解析（wf-api / 3000）

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
from astrbot.api.star import Context, Star, register

# 默认服务地址（可用 _conf_schema.json 里的配置覆盖）
WF_API = "http://127.0.0.1:3000"
WF_RAG = "http://127.0.0.1:8765"
TIMEOUT = 30

# 常见世界状态类型 -> 提示语（供 LLM 参考，不强制）
WS_TYPES = "电波|突击|裂缝|奸商|达尔沃|小小黑|钢铁之路|执刑官|仲裁|入侵|警报|双衍|科研|赏金|全局增益"


@register("astrbot_plugin_wfrag_tool", "小浅", "Warframe LLM 工具：Wiki RAG + 市价 + 世界状态 + 词库", "1.1.0")
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
        sellers = [{
            "name": (s.get("user") or {}).get("ingameName"),
            "price": s.get("platinum"),
            "qty": s.get("quantity"),
            "status": (s.get("user") or {}).get("status"),
        } for s in (d.get("seller") or [])[:3]]
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
            "top_sellers": sellers,
        }
        return json.dumps(out, ensure_ascii=False)

    # ---------- 工具 3：世界状态 ----------

    @filter.llm_tool(name="wf_world_state")
    async def wf_world_state(self, event: AstrMessageEvent, **kwargs) -> str:
        """查询 Warframe 当前世界状态（实时）

        用户问“现在有什么任务/活动”“电波本周任务”“奸商来了吗”“突击是什么”“钢铁之路轮换”等时调用。

        Args:
            type(string): 状态类型，支持中文/英文。常用：
                电波(nightwave)、突击(sortie)、裂缝(fissures)、奸商(voidTrader)、
                达尔沃(dailyDeals)、小小黑(persistentEnemies)、钢铁之路(steelPath)、
                执刑官(archonHunt)、仲裁(arbitration)、入侵(invasions)、警报(alerts)、
                双衍(duviriCycle)、科研(archimedeas)、全局增益(globalUpgrades)、
                地球/金星/火卫二/扎里曼 昼夜(earthCycle/vallisCycle/cambionCycle/zarimanCycle)

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

    # ---------- 工具 4：词库/黑话 ----------

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
        if not isinstance(d, list) or not d:
            return json.dumps({"success": False, "message": f"词库未找到「{kw}」"}, ensure_ascii=False)
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

    # ---------- 测试命令 ----------

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
                "Warframe LLM 工具插件 v1.1.0\n"
                f"服务状态：{self._health_line()}\n"
                "已注册 4 个 llm_tool：\n"
                "  wf_rag_search(query, top_k)   - Wiki 知识库检索\n"
                "  wf_market_price(item)         - 市价查询（支持黑话）\n"
                "  wf_world_state(type)          - 世界状态（电波/突击/奸商…）\n"
                "  wf_dict(keyword)              - 黑话/词库解析\n\n"
                "测试：/wfllm rag 电击异常 | price 奶妈P | ws 电波 | dict 三傻"
            )
            return
        tool, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
        try:
            if tool in ("rag", "search", "r"):
                res = await self.wf_rag_search(event, query=arg)
            elif tool in ("price", "wm", "p"):
                res = await self.wf_market_price(event, item=arg)
            elif tool in ("ws", "wf", "world", "w"):
                res = await self.wf_world_state(event, type=arg)
            elif tool in ("dict", "d"):
                res = await self.wf_dict(event, keyword=arg)
            else:
                yield event.plain_result(f"未知工具: {tool}，可用 rag|price|ws|dict")
                return
            yield event.plain_result(res)
        except Exception as e:
            logger.error(f"[wfrag_tool] 测试异常: {e}")
            yield event.plain_result(f"异常: {type(e).__name__}: {e}")

    async def terminate(self) -> None:
        logger.info("[wfrag_tool] 已卸载")

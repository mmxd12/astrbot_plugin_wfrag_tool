"""Warframe 配装推荐 + DPS 计算 + 社区配装搜索工具

三个 LLM 工具，集成到 astrbot_plugin_wfrag_tool 插件：
- wf_recommend_build: 基于伤害公式的最优 MOD 配装推荐
- wf_compare_weapons: 2-4 把武器对比，含 DPS 计算
- wf_search_builds: Overframe.gg 社区配装搜索
"""

import asyncio
import json
import math
import os
import re
import time
import threading
import urllib.parse
import urllib.request
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter

try:
    from .enemy_cache import resolve_enemy_async
except ImportError:
    from enemy_cache import resolve_enemy_async


class BuildToolsMixin:
    WF_WEAPON_SOURCES = {
        "Primary": "http://111.170.14.106:18511/weapons",
        "Secondary": "http://111.170.14.106:18511/weapons",
        "Melee": "http://111.170.14.106:18511/weapons",
    }
    OVERFRAME_BASE = "https://overframe.gg"
    OVERFRAME_UA = "WFRagTool/1.4 (Warframe Knowledge Bot)"
    # 敌人参数由 enemy_cache 统一提供，支持别名、缓存、Wiki 和虚空天使。
    WF_ENEMIES = {}
    WF_DAMAGE_BONUSES = {
        "Slash":{"ferrite":.85,"alloy":.5,"flesh":1.25,"clonedFlesh":1.25,"robotic":.75},"Impact":{"flesh":.75,"clonedFlesh":.75,"shield":1.5},"Puncture":{"ferrite":1.5,"shield":.8,"robotic":1.25},
        "Heat":{"clonedFlesh":1.25,"protoShield":.5,"infestedFlesh":1.5,"infested":1.25},"Cold":{"alloy":1.25,"shield":1.5,"fossilized":.75},"Electricity":{"robotic":1.5,"machinery":1.5},
        "Toxin":{"flesh":1.5,"protoShield":1.5,"machinery":1.25},"Blast":{"ferrite":.75,"machinery":1.75,"fossilized":1.5},"Corrosive":{"ferrite":1.75,"protoShield":.5,"fossilized":1.75},
        "Gas":{"infestedFlesh":1.5,"infested":1.75},"Magnetic":{"alloy":.5,"shield":1.75,"protoShield":1.75},"Radiation":{"alloy":1.75,"shield":.75,"robotic":1.25,"fossilized":.25,"infested":.5},"Viral":{"clonedFlesh":1.75,"machinery":.75,"infestedFlesh":.5,"infested":.5},
    }
    WF_ELEMENT_COMBOS = {frozenset(["Heat","Cold"]):"Blast",frozenset(["Heat","Electricity"]):"Radiation",frozenset(["Heat","Toxin"]):"Gas",frozenset(["Cold","Electricity"]):"Magnetic",frozenset(["Cold","Toxin"]):"Viral",frozenset(["Electricity","Toxin"]):"Corrosive"}

    def build_tools_init(self):
        """初始化工具状态，由主类 __init__ 调用"""
        self._wf_weapon_cache = {}
        self._wf_weapon_cache_time = 0
        self._wf_mod_db = None
        self._wf_build_cache = {}
        self._wf_overframe_cache = {}
        self._wf_overframe_cache_time = 0

    def _wf_fetch_all_weapons_sync(self) -> list[dict]:
        """同步获取所有武器数据（带缓存）"""
        now = time.time()
        if self._wf_weapon_cache and now - self._wf_weapon_cache_time < 3600:
            return list(self._wf_weapon_cache.values())
        result = []
        # 从我们的 API 获取武器数据（返回 {Primary:[...], Secondary:[...], Melee:[...]}）
        try:
            req = urllib.request.Request("http://111.170.14.106:18511/weapons", headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            for cat in ["Primary", "Secondary", "Melee"]:
                items = data.get(cat, [])
                for w in items:
                    if w.get("name"):
                        self._wf_weapon_cache[w.get("zh_name") or w["name"]] = w
                result.extend(items)
        except Exception as e:
            logger.warning(f"[wfrag_tool] Failed to fetch weapons: {e}")
        self._wf_weapon_cache_time = now
        return result

    async def _wf_fetch_all_weapons(self) -> list[dict]:
        return await asyncio.to_thread(self._wf_fetch_all_weapons_sync)

    def _wf_find_weapon(self, name: str) -> dict | None:
        q = name.lower().strip(); cache = self._wf_weapon_cache
        # 精确匹配缓存键
        for n, w in cache.items():
            if n.lower() == q: return w
            if (w.get("name") or "").lower() == q: return w
            if (w.get("zh_name") or "").lower() == q: return w
        # 模糊匹配
        c = [w for n,w in cache.items() if q in n.lower() or n.lower() in q
             or q in (w.get("name","").lower() or "") or q in (w.get("zh_name","").lower() or "")]
        return c[0] if len(c) == 1 else (min(c, key=lambda w: abs(len(w.get("name", ""))-len(name))) if c else None)

    def _wf_normalize_weapon(self, raw: dict) -> dict:
        dmg = raw.get("damage", {}) or {}
        damage = {k:v for k,v in dmg.items() if isinstance(v,(int,float)) and v > 0 and k != "total"}
        return {"name":raw.get("name","Unknown"),"zh_name":raw.get("zh_name") or raw.get("zhName") or raw.get("name",""),"type":raw.get("type",raw.get("weaponType","")),"category":raw.get("category",""),"damage":damage,"totalDamage":float(raw.get("totalDamage",sum(damage.values())) or sum(damage.values())),"criticalChance":float(raw.get("criticalChance",raw.get("critChance",0)) or 0),"criticalMultiplier":float(raw.get("criticalMultiplier",raw.get("critMultiplier",1)) or 1),"statusChance":float(raw.get("procChance",raw.get("statusChance",0)) or 0),"fireRate":float(raw.get("fireRate",1) or 1),"magazineSize":int(raw.get("magazineSize",30) or 30),"reloadTime":float(raw.get("reloadTime",2) or 2),"multishot":float(raw.get("multishot",1) or 1),"disposition":int(raw.get("disposition",1) or 1),"polarities":raw.get("polarities",[]),"trigger":raw.get("trigger",""),"masteryReq":int(raw.get("masteryReq",0) or 0),"raw":raw}

    def _wf_load_mod_db(self) -> dict:
        if self._wf_mod_db is not None: return self._wf_mod_db
        try:
            with open(os.path.join(os.path.dirname(__file__), "wf_mods_db.json"), encoding="utf-8") as f: self._wf_mod_db = json.load(f)
        except Exception as e:
            logger.warning(f"[wfrag_tool] Failed to load mod DB: {e}"); self._wf_mod_db = {}
        return self._wf_mod_db

    def _wf_get_compatible_mods(self, weapon_type: str) -> list[dict]:
        mp={"Rifle":"rifle","Sniper":"rifle","Bow":"rifle","Pistol":"pistol","Shotgun":"shotgun","Melee":"melee","Arch-Gun":"archgun","Archgun":"archgun"}; wt=mp.get(weapon_type,weapon_type.lower()); out=[]
        for n,m in self._wf_load_mod_db().items():
            types=m.get("weaponType",[]); types=[types] if isinstance(types,str) else types
            if wt in types or "all" in types or not types: out.append({"name":n,**m})
        return out

    def _wf_average_crit_multiplier(self, chance, multiplier):
        if chance <= 0: return 1.0
        if chance <= 1: return 1 + chance*(multiplier-1)
        whole=math.floor(chance); frac=chance-whole
        return multiplier**whole*(1-frac)+multiplier**(whole+1)*frac

    def _wf_calculate_dps(self, weapon, mods=None):
        total=weapon.get("totalDamage",1) or 1; base=sum(weapon.get("damage",{}).values()) or total
        bonus={"baseDamage":0,"multishot":0,"critChance":0,"critDamage":0,"fireRate":0,"statusChance":0}; elem={}; phys={}
        for mod in mods or []:
            s=mod.get("stats",{})
            for k in bonus: bonus[k]+=s.get(k,0)
            for k in ("Heat","Cold","Toxin","Electricity"): elem[k]=elem.get(k,0)+s.get(k,0)
            for k in ("Impact","Puncture","Slash"): phys[k]=phys.get(k,0)+s.get(k,0)
        ratio={k:v/total for k,v in weapon.get("damage",{}).items() if v>0}
        for k,v in list(ratio.items()):
            if k in ("Impact","Puncture","Slash"): ratio[k]*=1+phys.get(k,0)
        for k,v in elem.items(): ratio[k]=ratio.get(k,0)+v
        damage=total*(1+bonus["baseDamage"])*(sum(ratio.values())/total if total else 1)
        cc=max(0,weapon.get("criticalChance",0)*(1+bonus["critChance"])); cm=max(1,weapon.get("criticalMultiplier",1)*(1+bonus["critDamage"])); ms=max(0,weapon.get("multishot",1)*(1+bonus["multishot"])); fr=max(.01,weapon.get("fireRate",1)*(1+bonus["fireRate"])); st=max(0,weapon.get("statusChance",0)*(1+bonus["statusChance"]))
        ac=self._wf_average_crit_multiplier(cc,cm); burst=damage*ac*ms*fr; mag=max(1,weapon.get("magazineSize",30)); reload=max(0,weapon.get("reloadTime",2)); mt=mag/fr; sustained=mt/(mt+reload)*burst if mt+reload else burst
        return {"damage_per_shot":damage,"burst_dps":burst,"sustained_dps":sustained,"avg_crit_mult":ac,"eff_crit":cc,"eff_crit_mult":cm,"eff_status":st,"eff_multishot":ms,"eff_firerate":fr,"status_pps":st*ms*fr}

    def _wf_enemy_damage(self, weapon, dps_result, enemy, enemy_level=None):
        base=enemy.get("baseLevel",8); level=max(base,enemy_level or base); off=max(0,level-base); armor=enemy.get("baseArmor",0)*(1+off**1.75*.005) if enemy.get("armorType")!="none" else 0; af=300/(armor+300) if armor else 1; mult=dps_result["avg_crit_mult"]*dps_result["eff_multishot"]*dps_result["eff_firerate"]; damage=weapon.get("damage",{}); total=sum(v for v in damage.values() if v>0) or 1; ht=enemy.get("healthType","flesh"); st=enemy.get("shieldType","none") if enemy.get("baseShield",0)>0 else "none"; health=shield=bypass=0
        for typ,val in damage.items():
            if val<=0: continue
            p=val/total*weapon.get("totalDamage",1)*mult
            if st!="none" and typ!="Toxin": shield+=p*self.WF_DAMAGE_BONUSES.get(typ,{}).get(st,1)
            hb=self.WF_DAMAGE_BONUSES.get(typ,{}).get(ht,1)
            if typ=="Toxin": bypass+=p*hb
            else: health+=p*hb*self.WF_DAMAGE_BONUSES.get(typ,{}).get(enemy.get("armorType",""),1)*af
        sh=enemy.get("baseShield",0)*(1+off**2*.0075); hp=enemy.get("baseHealth",700)*(1+off**2*.015)
        if sh and shield: stime=sh/shield; htime=max(0,hp-bypass*stime)/max(1e-12,health) if health else 999; kt=stime+htime
        elif bypass: kt=hp/bypass
        elif health: kt=hp/health
        else: return 0
        return (hp+sh)/max(kt,.001)

    def _wf_select_mods(self, mods, goal, weapon):
        def score(m):
            s=m.get("stats",{});
            if goal=="crit": return s.get("critChance",0)*3+s.get("critDamage",0)*2+s.get("baseDamage",0)+s.get("multishot",0)
            if goal=="status": return s.get("statusChance",0)*3+s.get("fireRate",0)*2+s.get("baseDamage",0)
            if goal=="viral_slash": return s.get("Slash",0)*3+s.get("Toxin",0)*2+s.get("critChance",0)+s.get("baseDamage",0)
            if goal=="corrosive": return s.get("Electricity",0)*2+s.get("Toxin",0)*2+s.get("baseDamage",0)+s.get("multishot",0)
            return s.get("baseDamage",0)*2+s.get("multishot",0)*2+s.get("critChance",0)+s.get("critDamage",0)
        out=[]; seen_group=set(); seen_elem_stat=set()
        for m in sorted(mods,key=score,reverse=True):
            g=m.get("group","")
            # Dedup by group (only one baseDamage, one multishot, etc.)
            if g in seen_group and g not in ("elemental","physical"): continue
            # For elemental mods, dedup by stat key - keep strongest per element
            if g == "elemental":
                skip = False
                for stat_key in m.get("stats",{}):
                    if stat_key in ("Heat","Cold","Toxin","Electricity") and stat_key in seen_elem_stat:
                        skip = True; break
                if skip: continue
                for stat_key in m.get("stats",{}):
                    if stat_key in ("Heat","Cold","Toxin","Electricity"): seen_elem_stat.add(stat_key)
            seen_group.add(g); out.append(m)
            if len(out)>=8: break
        return out

    @filter.llm_tool(name="wf_recommend_build")
    async def wf_recommend_build(self, event: AstrMessageEvent, **kwargs) -> str:
        """根据武器名和流派推荐最优 MOD 配装。
        
        Args:
            weapon(string): 武器名（中英文皆可，如 "舍杜" "Shedu"）
            goal(string): 配装流派。可选：general_dps(均衡DPS/默认), crit(暴击流), status(触发流), viral_slash(病毒切), corrosive(腐蚀)
            enemy(string): 攻击目标敌人名（可选，钢 path 重甲兵等）
            enemy_level(int): 敌人等级（可选，默认使用基础等级）
        """
        weapon_name=str(kwargs.get("weapon","")).strip(); goal=str(kwargs.get("goal","general_dps")).strip(); enemy=str(kwargs.get("enemy","")).strip()
        try: level = int(kwargs.get("enemy_level")) if kwargs.get("enemy_level") is not None else None
        except (TypeError, ValueError): level = None
        if not weapon_name: return json.dumps({"success":False,"message":"缺少参数 weapon（武器名）"},ensure_ascii=False)
        await self._wf_fetch_all_weapons(); raw=self._wf_find_weapon(weapon_name)
        if not raw: return json.dumps({"success":False,"message":f"未找到武器「{weapon_name}」"},ensure_ascii=False)
        w=self._wf_normalize_weapon(raw); mods=self._wf_get_compatible_mods(w["type"])
        if not mods: return json.dumps({"success":False,"message":f"未找到适合 {self._type_zh(w['type'])} 类型的 MOD"},ensure_ascii=False)
        selected=self._wf_select_mods(mods,goal,w); d=self._wf_calculate_dps(w,selected); ed=None; enemy_data=None; enemy_label=enemy
        if enemy:
            enemy_data = await resolve_enemy_async(enemy)
            if enemy_data:
                enemy_label = enemy_data.get("name") or enemy
                ed = self._wf_enemy_damage(w, d, enemy_data, level)
        lines=[f"🎯 {w.get('zh_name') or w['name']} 推荐配装（{goal}）","","【MOD 配置】"]
        for i,m in enumerate(selected,1):
            desc=", ".join(f"{self._stat_zh(k)} {v:+.0%}" for k,v in m.get("stats",{}).items()); lines.append(f"  {i}. {m.get('name', m.get('en', m.get('n', '?')))} ({m.get('group','')}) — {desc} [drain:{m.get('drain',0)}]")
        lines += ["","【DPS 数据】",f"  单发伤害: {d['damage_per_shot']:.1f}",f"  暴击倍率: {d['avg_crit_mult']:.2f}x (有效暴击率: {d['eff_crit']:.0%})",f"  爆发 DPS: {d['burst_dps']:.0f}",f"  持续 DPS: {d['sustained_dps']:.0f}",f"  触发/秒: {d['status_pps']:.1f}"]
        if ed is not None:
            lines += ["", f"【对 {enemy_label} 有效 DPS】  {ed:.0f}"]
            if enemy_data.get("weaknesses"):
                lines.append("  敌人弱点：" + "、".join(enemy_data["weaknesses"]))
            if enemy_data.get("mechanics"):
                lines.append("  敌人机制：" + "；".join(enemy_data["mechanics"]))
        return "\n".join(lines)

    @filter.llm_tool(name="wf_compare_weapons")
    async def wf_compare_weapons(self,event: AstrMessageEvent,**kwargs)->str:
        """对比 2-4 把武器的属性，可选配装 DPS 计算。
        
        Args:
            weapons(string): 武器名列表，逗号分隔（如 "舍杜, 迅发电浆炮"）
            include_build(bool): 是否包含推荐 MOD DPS 计算，默认 false
        """
        text=str(kwargs.get("weapons","")).strip(); inc=str(kwargs.get("include_build","false")).lower()=="true"
        if not text: return json.dumps({"success":False,"message":"缺少参数 weapons（武器名，逗号分隔）"},ensure_ascii=False)
        names=[x.strip() for x in text.split(",") if x.strip()][:4]
        if len(names)<2: return json.dumps({"success":False,"message":"至少需要 2 把武器进行对比"},ensure_ascii=False)
        await self._wf_fetch_all_weapons(); ws=[self._wf_normalize_weapon(x) for n in names if (x:=self._wf_find_weapon(n))]
        if len(ws)<2: return json.dumps({"success":False,"message":"有效武器不足 2 把"},ensure_ascii=False)
        h=[w.get("zh_name") or w["name"] for w in ws]; rows=[("总伤害",[f"{w['totalDamage']:.0f}" for w in ws]),("暴击率",[f"{w['criticalChance']:.0%}" for w in ws]),("暴击倍率",[f"{w['criticalMultiplier']:.0f}x" for w in ws]),("触发率",[f"{w['statusChance']:.0%}" for w in ws]),("射速",[f"{w['fireRate']:.1f}" for w in ws]),("弹匣",[str(w['magazineSize']) for w in ws]),("换弹",[f"{w['reloadTime']:.1f}s" for w in ws]),("段位需求",[f"MR {w['masteryReq']}" for w in ws])]; lines=[f"⚔ 武器对比（{len(ws)} 把）","", "| 属性 | "+" | ".join(h)+" |","| --- | "+" | ".join(["---"]*len(h))+" |"]+[f"| {k} | "+" | ".join(v)+" |" for k,v in rows]
        if inc:
            ds=[self._wf_calculate_dps(w,self._wf_select_mods(self._wf_get_compatible_mods(w["type"]),"general_dps",w)) for w in ws]; lines += ["","【推荐 MOD DPS】","| 指标 | "+" | ".join(h)+" |","| --- | "+" | ".join(["---"]*len(h))+" |",f"| 爆发 DPS | "+" | ".join(f"{d['burst_dps']:.0f}" for d in ds)+" |",f"| 持续 DPS | "+" | ".join(f"{d['sustained_dps']:.0f}" for d in ds)+" |"]
        return "\n".join(lines)

    async def _wf_overframe_get(self,url,timeout=30):
        def get():
            req=urllib.request.Request(url,headers={"User-Agent":self.OVERFRAME_UA,"Accept":"text/html,application/xhtml+xml,application/json"})
            with urllib.request.urlopen(req,timeout=timeout) as r: return r.read().decode("utf-8",errors="replace")
        return await asyncio.to_thread(get)

    def _wf_parse_sitemap(self,xml_text):
        p=re.compile(r"<loc>\s*https://overframe\.gg/items/arsenal/(\d+)/([^<]+?)/\s*</loc>",re.I); out=[]
        for m in p.finditer(xml_text):
            slug=m.group(2).strip(); out.append({"id":int(m.group(1)),"slug":slug,"name":" ".join(x[:1].upper()+x[1:] for x in slug.split("-")),"url":f"{self.OVERFRAME_BASE}/items/arsenal/{m.group(1)}/{slug}/"})
        return out

    def _wf_normalize_text(self,text):
        import unicodedata
        text=unicodedata.normalize("NFKD",text); text="".join(c for c in text if not unicodedata.combining(c)); text=text.lower(); text=re.sub(r"\bsteelpath\b","steel path",text); text=re.sub(r"\bsp\b","steel path",text); text=re.sub(r"\blevelcap\b","level cap",text); return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9]+"," ",text)).strip()

    async def _wf_resolve_overframe_item(self,item_name):
        key="overframe:sitemap"; cached=self._wf_overframe_cache.get(key)
        if cached and time.time()-self._wf_overframe_cache_time<432000: items=cached
        else:
            try: items=self._wf_parse_sitemap(await self._wf_overframe_get(f"{self.OVERFRAME_BASE}/sitemap.xml")); self._wf_overframe_cache[key]=items; self._wf_overframe_cache_time=time.time()
            except Exception as e: logger.warning(f"[wfrag_tool] Overframe sitemap failed: {e}"); return None
        q=self._wf_normalize_text(item_name)
        for x in items:
            if self._wf_normalize_text(x["name"])==q or x["slug"].lower()==q.replace(" ","-"): return x
        c=[x for x in items if q in self._wf_normalize_text(x["slug"])]
        return c[0] if len(c)==1 else None

    @filter.llm_tool(name="wf_search_builds")
    async def wf_search_builds(self,event: AstrMessageEvent,**kwargs)->str:
        """搜索 Overframe.gg 社区配装方案。
        
        Args:
            item(string): 武器/物品名（中英文皆可）
            filter(string): 可选过滤条件（如热门/最新/高评分）
            limit(int): 返回数量，默认5，最多10
        """
        name=str(kwargs.get("item","")).strip(); filt=str(kwargs.get("filter","") or "").strip()
        if not name: return json.dumps({"success":False,"message":"缺少参数 item（物品名）"},ensure_ascii=False)
        try: limit=max(1,min(int(kwargs.get("limit",5) or 5),10))
        except (TypeError,ValueError): limit=5
        item=await self._wf_resolve_overframe_item(name)
        if not item: return f"未在 Overframe.gg 找到「{name}」，请检查名称拼写。"
        try: html=await self._wf_overframe_get(item["url"])
        except Exception as e: return f"无法访问 Overframe.gg: {e}"
        m=re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',html,re.I|re.S)
        if not m: return "Overframe.gg 页面解析失败。"
        try: builds=json.loads(m.group(1)).get("props",{}).get("pageProps",{}).get("builds",[])
        except json.JSONDecodeError: return "Overframe.gg 数据解析失败。"
        unique={b.get("id"):b for b in builds if b.get("id")}; builds=sorted(unique.values(),key=lambda b:float(b.get("score",0) or 0),reverse=True)
        if filt:
            groups=[self._wf_normalize_text(x).split() for x in filt.split(",") if x.strip()]; builds=[b for b in builds if any(all(w in self._wf_normalize_text(b.get("title","")) for w in g) for g in groups)]
        builds=builds[:limit]
        if not builds: return f"在 Overframe.gg 未找到匹配的配装（物品: {name}，过滤: {filt or '无'}）"
        lines=[f"📦 Overframe.gg 配装 - {item.get('name', m.get('en', m.get('n', '?')))}",""]
        for i,b in enumerate(builds,1): lines += [f"{i}. {b.get('title','Untitled')}",f"   👍 {int(float(b.get('score',0) or 0))} 票 | 🔄 {b.get('formas','?')} F | 👤 {(b.get('author') or {}).get('username','?')} | 📅 {str(b.get('updated',''))[:10]}",f"   🔗 {self.OVERFRAME_BASE}/build/{b.get('id','')}",""]
        return "\n".join(lines)

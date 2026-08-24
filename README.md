# astrbot_plugin_wfrag_tool

AstrBot Warframe LLM 工具插件：配装推荐 + DPS 计算 + 社区配装搜索 + 实时数据查询

## 功能

### 直接命令（任意前缀触发）

| 命令 | 功能 |
|------|------|
| `配装 武器名 [流派] [打敌人]` | 配装推荐（现场数值计算） |
| `武器对比 武器1, 武器2, ...` | 2-4 把武器对比 + DPS |
| `搜配装 武器名` | 搜索 Overframe 社区配装 |
| `紫卡分析` | 紫卡品质分析（截图 OCR） |
| `wfllm <工具> <参数>` | 统一工具入口 |

**配装流派：**
- 暴击流（crit）
- 触发流（status）
- 病毒切（viral_slash）
- 腐蚀流（corrosive）
- 默认均衡 DPS（general_dps）

**配装示例：**
```
配装 舍杜                  → 均衡配装
配装 舍杜 暴击流            → 暴击流派
配装 舍杜 打虚空天使         → 针对虚空天使配装
武器对比 舍杜, 迅发电浆炮    → 武器对比
搜配装 舍杜                → 社区配装
```

### LLM 工具（function calling 自动调用 / wfllm 指令入口）

| 工具名 | 功能 | wfllm 指令 |
|--------|------|-----------|
| `wf_recommend_build` | 配装推荐 | 配装 武器名 [流派] |
| `wf_compare_weapons` | 武器对比 | 武器对比 武器1, 武器2 |
| `wf_search_builds` | 社区配装搜索 | 搜配装 武器名 |
| `wf_world_state` | 世界状态 | `wfllm ws 世界状态名称`（如 wfllm ws 电波） |
| `wf_market_price` | 市价查询 | `wfllm price 物品名`（如 wfllm price 奶妈P） |
| `wf_riven_price` | 紫卡拍卖查询 | `wfllm riven 武器名`（如 wfllm riven 食人女魔） |
| `wf_lich_price` | 玄骸/姐妹市场价 | `wfllm lich 武器名` |
| `wf_rag_search` | Wiki 知识检索 | `wfllm rag 问题` |
| `wf_arbitration_essence` | 仲裁精华表 | `wfllm arb` |
| `wf_dict` | 词库查询 | `wfllm dict 关键词` |

**测试指令（wfllm）：**
```
wfllm rag 电击异常
wfllm price 奶妈P
wfllm riven 食人女魔
wfllm lich 食人女魔
wfllm ws 电波
wfllm arb
wfllm dict 三傻
```

## 数据源

所有数据通过 warframe-info-api 获取：
- 武器数据：`/weapons`（WFCD + 中文名归并）
- MOD 数据：`/mods`（1806 个 MOD，数值化）
- 敌人数据：灰机 Wiki + 本地缓存兜底
- 市价/紫卡/世界状态：warframe-info-api

中文名多数据源归并（DE 官方 > WFA > browse.wf > 原文），每 3 小时自动刷新。

## 依赖

- warframe-info-api（需部署）
- rapidocr-onnxruntime（紫卡 OCR）
- 灰机 Wiki API（敌人数据，可选）
- [本地rag](https://github.com/mmxd12/wf-rag-pack)（这个是本地wiki与上方同源，请选择其一，可选）
# astrbot_plugin_wfrag_tool

AstrBot Warframe LLM 工具插件：配装推荐 + DPS 计算 + 社区配装搜索 + 实时数据查询

## 功能

### 直接命令（任意前缀触发）

| 命令 | 功能 |
|------|------|
| `配装 武器/战甲名 [流派] [打敌人/环境]` | 武器/战甲配装推荐（自动识别） |
| `武器对比 武器1, 武器2, ...` | 2-4 把武器对比 + DPS |
| `搜配装 武器名` | 搜索 Overframe 社区配装 |
| `紫卡分析` | 紫卡品质分析（截图 OCR） |
| `wfllm <工具> <参数>` | 统一工具入口 |

**配装流派（武器）：**
- 暴击流（crit）
- 触发流（status）
- 病毒切（viral_slash）
- 腐蚀流（corrosive）
- 默认均衡 DPS（general_dps）

**配装流派（战甲）：**
- 生存
- 强度
- 效率
- 范围
- 均衡（默认）

**支持环境/场景（打XXX）：**
科研、钢铁之路、仲裁、夜灵、指数、扎里曼、九重天、平原、墓地、赤毒、虚空、警报

**配装示例：**
```
配装 舍杜                  → 武器配装（均衡）
配装 舍杜 暴击流            → 武器暴击流派
配装 哪吒 打豺狼            → 战甲配装 + 敌人感知
配装 悟空p 打钢铁之路        → 战甲黑话（悟空P）+ 环境感知
配装 咖喱棒 打科研           → 战甲黑话（咖喱棒=Excalibur）
武器对比 舍杜, 迅发电浆炮    → 武器对比
搜配装 舍杜                → 社区配装
```

**战甲黑话支持：**
奶妈(Trinity)、电男(Volt)、dj(Octavia)、猴/悟空(Wukong)、土甲(Atlas)、龙甲(Chroma)、猫甲(Khora)、毒妈(Saryn)、咖喱棒(Excalibur)、肥宅(Grendel) 等 208+ 条（来自 warframe-info-api 的 alias_local.json）

### LLM 工具（function calling 自动调用 / wfllm 指令入口）

| 工具名 | 功能 | wfllm 指令 |
|--------|------|-----------|
| `wf_recommend_build` | 武器配装推荐 | `配装 武器名 [流派]` |
| `wf_recommend_warframe_build` | 战甲配装推荐 | `配装 战甲名 [流派]` |
| `wf_compare_weapons` | 武器对比 | `武器对比 武器1, 武器2` |
| `wf_search_builds` | 社区配装搜索 | `搜配装 武器名` |
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

所有数据通过 warframe-info-api 获取（多源兜底）：

| API | 数据 |
|-----|------|
| `/weapons` | 武器数据（WFCD + 中文名） |
| `/mods` | MOD 数据（1806 个，数值化） |
| `/warframes` | 战甲数据（121 个 + 黑话别名） |
| 敌人数据 | 灰机 Wiki + 本地缓存兜底 |
| 环境数据 | 本地 environment_data.py（12 种环境） |

中文名多数据源归并（DE 官方 > WFA > browse.wf > 原文），每 3 小时自动刷新。
MOD 动态补齐：本地不足时自动从 /mods API 拉全量数据。

## 依赖

- warframe-info-api（需部署）
- rapidocr-onnxruntime（紫卡 OCR）
- 灰机 Wiki API（敌人数据，可选）

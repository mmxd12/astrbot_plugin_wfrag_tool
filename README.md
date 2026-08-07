# astrbot_plugin_wfrag_tool — Warframe LLM 工具

给 AstrBot 注册 **4 个 LLM 工具**（function calling），让 AI 在对话中主动查询 Warframe 实时数据与 Wiki 知识库：

| 工具 | 功能 | 后端 |
|---|---|---|
| `wf_rag_search(query, top_k)` | 检索 Warframe 中文 Wiki 知识库，返回权威机制/数值片段+出处 | wf-rag (8765) |
| `wf_market_price(item)` | Warframe Market 市价查询，**支持玩家黑话**（奶妈P/福马/三傻…） | wf-api (3000) |
| `wf_world_state(type)` | 世界状态：电波/突击/裂缝/奸商/达尔沃/钢铁之路/执刑官/仲裁… | wf-api (3000) |
| `wf_dict(keyword)` | 词库/黑话解析：黑话 → 正式英文名 | wf-api (3000) |

## 依赖的两个本地服务

```bash
# 1. wf-api（Node，端口 3000）：市价 / 世界状态 / 词库
cd wf-api && npm start

# 2. wf-rag（Python，端口 8765）：Wiki 检索
cd wf-rag && python server.py      # 索引缺失时先 python build_index.py
```

服务未启动时工具会返回可读错误提示，不影响 LLM 其他能力。

## 启动自检（v1.1.0 新增）

插件加载时会**自动探活**两个后端服务（只检查 HTTP 可达性，不依赖任何数据）：

- 全部在线 → 日志输出 `[wfrag_tool] 启动自检通过：wf-api ✓ | wf-rag ✓`
- 某个离线 → 日志输出醒目警告，如 `⚠ wf-api 未连接（市价/世界状态/词库工具将不可用）`

随时运行 `/wfllm` 也能看到实时状态行：`wf-api: ✓ 在线 | wf-rag: ✗ 离线`。
如果显示离线，按上面"依赖的两个本地服务"把服务跑起来即可，无需重启 AstrBot。

## 部署

1. 本目录放到 `data/plugins/astrbot_plugin_wfrag_tool/`（目录名必须 `astrbot_plugin_` 开头）
2. 重启 AstrBot，在插件管理启用
3. 可在插件配置里改 `wf_api_url` / `wf_rag_url` / `timeout`

## 测试

- `/wfllm` — 查看工具清单
- `/wfllm rag 电击异常` — 测试 RAG 检索
- `/wfllm price 奶妈P` — 测试市价
- `/wfllm ws 电波` — 测试世界状态
- `/wfllm dict 三傻` — 测试词库

源码同步维护在 `wf-rag/llm_tool.py`（本目录 main.py 为其副本）。
自测脚本：`wf-rag/test_llm_tool.py` —— **零依赖**（mock 掉 AstrBot 装饰器），
任意 Python 3.10+ 直接 `python test_llm_tool.py` 即可验证 4 个工具，只需 wf-api/wf-rag 服务在线。

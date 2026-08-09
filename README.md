# astrbot_plugin_wfrag_tool — Warframe LLM 工具

给 AstrBot 注册 **4 个 LLM 工具**（function calling），让 AI 在对话中主动查询 Warframe 实时数据与 Wiki 知识库：

| 工具 | 功能 | 后端 |
|---|---|---|
| `wf_rag_search(query, top_k)` | 检索 Warframe 中文 Wiki 知识库，返回权威机制/数值片段+出处 | wf-rag (8765) |
| `wf_market_price(item)` | Warframe Market 市价查询，**支持玩家黑话**（奶妈P/福马/三傻…） | wf-api (3000) |
| `wf_world_state(type)` | 世界状态：电波/突击/裂缝/钢铁裂缝/九重天/奸商/达尔沃/钢铁之路/执刑官/仲裁/赏金(科维兽/1999)… | wf-api (3000) |
| `wf_dict(keyword)` | 词库/黑话解析：黑话 → 正式英文名 | wf-api (3000) |

## 🚀 一键安装（3 种方式任选）

**方式一：AstrBot 插件管理直接安装（最推荐，零命令行）**
AstrBot 后台 → 插件管理 → 安装插件 → 粘贴仓库地址：
```
https://github.com/mmxd12/astrbot_plugin_wfrag_tool
```
自动安装完成后重启 AstrBot 并启用即可。

**方式二：`wf-rag-pack` 一键安装脚本（自动探测 AstrBot 目录）**
```bash
git clone https://github.com/mmxd12/wf-rag-pack
cd wf-rag-pack
python install_plugin.py        # 自动找插件目录；找不到用 --target 指定
```

**方式三：手动放置**
把本目录（内含 main.py / metadata.yaml / _conf_schema.json）放到
`data/plugins/astrbot_plugin_wfrag_tool/`，重启 AstrBot 并在插件管理启用。

> 装完即用，无需手动配置：`wf_api_url` 默认已指向云端共享服务
> `https://wf.nana7mi.top`（市价/世界状态/词库开箱可用）。
> `wf_rag_url` 默认 `http://127.0.0.1:8765`，需自行部署 [wf-rag-pack](https://github.com/mmxd12/wf-rag-pack) 的检索服务。

## 后端服务（可选自建）

```bash
# 1. wf-api（Node，端口 3000）：市价 / 世界状态 / 词库
cd wf-api && npm start

# 2. wf-rag（Python，端口 8765）：Wiki 检索
cd wf-rag && python server.py      # 索引缺失时先 python build_index.py
```

服务未启动时工具会返回可读错误提示，不影响 LLM 其他能力。

### 重要组件
RAG 检索（Wiki 知识库）依赖 [wf-rag-pack](https://github.com/mmxd12/wf-rag-pack) 索引，
部署方式见该仓库 README（fetch.py → build_slang.py → build_index.py → server.py）。
若仅需市价/世界状态/词库（wf-api），无需安装 wf-rag。

## 启动自检（v1.2.0）

插件加载时会**自动探活**两个后端服务（只检查 HTTP 可达性，不依赖任何数据）：

- 全部在线 → 日志输出 `[wfrag_tool] 启动自检通过：wf-api ✓ | wf-rag ✓`
- 某个离线 → 日志输出醒目警告，如 `⚠ wf-api 未连接（市价/世界状态/词库工具将不可用）`

随时运行 `/wfllm` 也能看到实时状态行：`wf-api: ✓ 在线 | wf-rag: ✗ 离线`。
如果显示离线，按上面"后端服务"把服务跑起来即可，无需重启 AstrBot。

## 配置项（插件管理 → 插件配置里可改）

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `wf_api_url` | `https://wf.nana7mi.top` | 云端共享服务，装完即用 |
| `wf_rag_url` | `http://127.0.0.1:8765` | 与 AstrBot 同机 Docker 时填 `http://172.17.0.1:8765` |
| `timeout` | 30 | HTTP 超时（秒） |

## 测试

- `/wfllm` — 查看工具清单与后端在线状态
- `/wfllm rag 电击异常` — 测试 RAG 检索
- `/wfllm price 奶妈P` — 测试市价
- `/wfllm ws 电波` — 测试世界状态
- `/wfllm dict 三傻` — 测试词库

源码同步维护在 `wf-rag/llm_tool.py`（本目录 main.py 为其副本）。
自测脚本：`wf-rag/test_llm_tool.py` —— **零依赖**（mock 掉 AstrBot 装饰器），
任意 Python 3.10+ 直接 `python test_llm_tool.py` 即可验证 4 个工具，只需 wf-api/wf-rag 服务在线。

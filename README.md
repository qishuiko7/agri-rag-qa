# 农技通 · 农业智能问答助手

基于 **LangChain + RAG** 的农业垂直领域问答系统，最终升级为具备**工具调用能力的 Agent**。

严格按《案例5 农业智能问答助手（基于 LangChain RAG）》文档的七大模块、六大页面、
三周周期与笔记本轻量化约束实现，全部组件单机运行，无需服务器、独立显卡与数据库服务。

---

## 一、项目能力

### 阶段一：RAG 问答系统（对齐文档）

| 模块 | 实现情况 |
|---|---|
| 语料预处理与知识库管理 | 多格式导入（TXT/MD/PDF/CSV）、分批加载、在线预览、四大类归档、重复与异常筛查、删除与重命名 |
| 文本切片与向量库构建 | chunk_size=500 / overlap=50、中文标点断句、Chroma 文件型向量库、新建/追加/重置、入库进度实时展示 |
| 农业 RAG 智能问答 | 语义检索 top-k（默认 5）、农业专属 Prompt、云端大模型生成、非农问题关键词拦截 |
| 多轮对话管理 | 会话隔离、最近 5 轮上下文记忆、一键清空、时序展示 |
| 对话记录管理与统计 | JSONL 自动持久化、时间/关键词检索、基础统计、CSV 导出、单条与批量删除 |
| 前端交互与可视化 | 六大页面、问答气泡、状态展示、异常弹窗 |
| 系统基础设置 | 模型接口配置、检索参数、连通性测试、日志精简 |

### 阶段二：Agent 升级

在 RAG 之上引入 **Function Calling**，让模型自主决定调用哪些工具、调用几次：

| 工具 | 作用 |
|---|---|
| `search_knowledge` | 农业知识库语义检索（核心） |
| `crop_calendar` | 农事日历：按作物与月份给出关键农事节点 |
| `get_weather` | 农事气象：未来天气 + 低温/高温/降雨/大风影响提示 |
| `diagnose_symptom` | 症状初诊：叶黄、卷曲、斑点、萎蔫、烂根等启发式排查 |
| `calc_fertilizer` | 施肥量估算：按目标产量与土壤肥力折算氮磷钾与实物量 |
| `calc_dilution` | 农药稀释：按倍数或 ppm 计算用药量 |

Agent 与纯 RAG 可在问答页一键切换，工具调用轨迹全程可视化并写入历史记录。

---

## 二、技术栈

| 层次 | 选型 |
|---|---|
| 后端 | Python 3.10 + FastAPI + Uvicorn |
| RAG 框架 | LangChain 0.3（RecursiveCharacterTextSplitter / Chroma 集成） |
| 向量库 | Chroma 0.6（纯文件存储，无独立服务） |
| 嵌入模型 | 阿里云百炼 `text-embedding-v3`（1024 维）/ 智谱 `embedding-3` / Mock |
| 对话模型 | 百炼 `qwen-plus` / 智谱 `glm-4-flash`（OpenAI 兼容协议统一接入） |
| 前端 | Vue 3 + Vite 6 + Vue Router（无 UI 框架，纯手写样式） |
| 数据持久化 | JSONL（对话记录）+ 文件系统（语料）+ Chroma（向量） |

> 嵌入与对话均通过 OpenAI 兼容端点调用，一份代码同时支持百炼与智谱，
> 无需引入各家专用 SDK。

---

## 三、目录结构

```
agri-rag-qa/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口，静态资源托管
│   │   ├── config.py            # 全局配置（.env 驱动）
│   │   ├── core/
│   │   │   ├── loader.py        # 多格式加载（TXT/MD/PDF/CSV）
│   │   │   ├── cleaner.py       # 清洗去重、广告噪声过滤
│   │   │   ├── splitter.py      # 中文友好切片（500/50）
│   │   │   ├── llm.py           # 对话与嵌入客户端（含 Mock 降级）
│   │   │   ├── vectorstore.py   # Chroma 文件型向量库管理
│   │   │   ├── ingest.py        # 入库编排与进度追踪
│   │   │   ├── rag.py           # RAG 问答主链路
│   │   │   ├── guard.py         # 农业领域拦截
│   │   │   ├── prompts.py       # 提示词模板
│   │   │   ├── memory.py        # 多轮会话记忆
│   │   │   └── history.py       # 对话记录持久化与统计
│   │   ├── api/                 # 五组 REST 接口 + Agent 接口
│   │   └── agent/
│   │       ├── executor.py      # Function Calling 多步推理循环
│   │       └── tools/           # 六个 Agent 工具
│   └── data/
│       ├── corpus/              # 语料（planting/pest/breeding/general）
│       ├── chroma/              # 向量库持久化
│       └── records/             # 对话记录 JSONL
├── frontend/
│   ├── src/views/               # 六个页面
│   ├── src/api/index.js         # 接口封装 + SSE
│   └── dist/                    # 构建产物（由后端托管）
├── scripts/
│   ├── crawl_corpus.py          # 农业语料抓取（并发、清洗、分类）
│   ├── curate_corpus.py         # 语料后处理：剔除新闻、重新分类
│   ├── selftest.py              # 核心模块自测（43 项）
│   └── bench.py                 # 性能基准测试
├── start.py                     # 一键启动
└── .env                         # 密钥与参数
```

---

## 四、实测指标

测试环境：Windows 11 / Python 3.10.11 / 16GB 内存。系统支持两种模式，数据分别记录。

| 指标 | 真实模型模式（qwen-plus + text-embedding-v3） | Mock 模式 |
|---|---|---|
| 语料规模 | 598 篇 · 85.8 万字 | 同 |
| 向量库 | 2270 片段 · 35.1 MB · 1024 维 | 2270 片段 · 36.3 MB |
| 入库耗时 | 122 秒 | 24.5 秒 |
| 启动耗时 | 约 4 秒（含缓存预热 0.7 秒） | 约 4 秒 |
| 检索延迟 | 平均 208 ms · P95 282 ms | 平均 20 ms · P95 28 ms |
| 问答链路 | 平均 6.6 秒（首字约 700 ms） | 平均 27 ms |
| Agent 链路 | 平均 7.4 秒 | 平均 33 ms |
| 内存占用 | 236 MB | 228 MB |
| 知识库列表 | 预热后 7 ms | 同 |
| 核心自测 | 43 项 + 28 项接口全通过 | 同 |

> 真实模式的检索延迟里，绝大部分是嵌入接口的网络往返（本地向量计算仅 20 ms）；
> 问答 6.6 秒主要消耗在云端模型生成，流式模式下首字约 700 ms，感知流畅。
> Mock 模式用于无密钥时的链路验证与离线演示，数值反映系统自身开销，不含网络往返。

### 质量评测

「准确率」对 RAG 是个含糊说法——它把检索、生成、拦截三个环节混成一个数。
本项目分开度量，脚本可复现：`python scripts/evaluate.py`

| 指标 | 数值 | 测试集 |
|---|---|---|
| 检索 Recall@1 | 64.0% | 25 题，人工标注期望文档 |
| 检索 Recall@3 | 84.0% | 同上 |
| 检索 Recall@5 | **88.0%** | 同上 |
| 检索 MRR | 0.741 | 同上 |
| 回答要点覆盖率 | **95.0%** | 10 题，标注 1~3 个关键要点 |
| 领域拦截准确率 | **100.0%** | 15 个农业问题 + 15 个非农问题 |
| 拦截精确率 / 召回率 | 100% / 100% | 零误拦、零漏放 |

> 测试集的问题用农户口吻编写，不照抄文档标题，否则等于把答案关键词直接喂给检索器。
> 完整结果与分析见 `docs/eval-report.json` 与软件工程文档 5.3.2 节。
>
> **注意局限**：25 题的置信区间约 ±12 个百分点，88% 与 80% 在统计上不可区分；
> 要点覆盖只检查关键词是否出现，不判断表述准确性。

---

## 五、快速开始

### 1. 环境要求

- Python 3.8 ~ 3.10（推荐 3.10，兼容性最好）
- Node.js 18+（仅构建前端时需要，构建产物已随项目提供）

### 2. 安装依赖

```bash
# 后端
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r backend/requirements.txt

# 前端（可选，dist 已构建好）
cd frontend && npm install && npm run build && cd ..
```

### 3. 配置模型

编辑项目根目录 `.env`：

```ini
DASHSCOPE_API_KEY=sk-ws-xxxx      # 百炼 API Key，对话+向量化同一把
LLM_PROVIDER=dashscope
LLM_MODEL=qwen-plus
EMBEDDING_PROVIDER=dashscope
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_DIM=1024
```

> **Key 格式注意**：百炼控制台会给出多种凭据，只有 `sk-` 或 `sk-ws-` 开头的 API Key
> 能调用 REST 接口。`o1_` 开头的是 Bailian CLI 专用凭据，调用 API 会返回 401。
> 智谱的 Key 形如 `{id}.{secret}`，作为备用提供方填入 `ZHIPU_API_KEY` 即可。

> 不填密钥也能启动：系统自动降级为 **Mock 模式**，
> 检索、入库、记录、导出等链路完整可用，只是回答内容是占位文本。

### 4. 准备语料

```bash
# 方式一：从中国农业农村信息网抓取（约 680 篇，清洗后保留约 600 篇）
python scripts/crawl_corpus.py --workers 5

# 抓取后可执行清洗，剔除新闻类内容并按内容重新分类
python scripts/curate_corpus.py --apply

# 方式二：把自有文档放入 backend/data/corpus/<分类>/ 目录
#   planting=种植技术  pest=病虫害防治  breeding=养殖技术  general=通用农技
```

> 内置语料实测：抓取 681 篇 → 清洗剔除 83 篇新闻/短讯 → 保留 **598 篇**、
> 85.8 万字，切出 **2270 个片段**。分类分布：种植 503、病虫害 48、养殖 26、通用 21。
> 语料源以种植业为主，养殖类偏少，可自行补充到 `corpus/breeding/`。

### 5. 启动

```bash
python start.py
```

访问 <http://127.0.0.1:8000>，首次使用先到「向量库构建」页执行一次入库。

---

## 六、关键参数

| 参数 | 默认值 | 说明 | 文档依据 |
|---|---|---|---|
| `CHUNK_SIZE` | 500 | 切片长度（字符） | 第七章「切片固定默认值」 |
| `CHUNK_OVERLAP` | 50 | 切片重叠 | 同上 |
| `TOP_K` | 5 | 单次召回条数 | 「检索数量限制：最多 5 条」 |
| `BATCH_SIZE` | 30 | 分批加载文档数 | 「每次仅加载 20~50 份」 |
| `MEMORY_ROUNDS` | 5 | 多轮记忆轮数 | 「仅保留最近 5 轮」 |

日志级别设为 WARNING，仅保留错误日志，对应「日志精简」要求。

---

## 七、接口一览

| 分组 | 接口 | 说明 |
|---|---|---|
| 对话 | `POST /api/chat/ask` | 非流式问答（mode=rag/agent） |
| | `GET /api/chat/stream` | SSE 流式问答 |
| | `POST /api/chat/clear` | 清空会话记忆 |
| | `GET /api/chat/status` | 系统运行状态 |
| 知识库 | `GET /api/kb/stats` | 语料统计 |
| | `GET /api/kb/documents` | 文档列表（含异常标记） |
| | `POST /api/kb/upload` | 批量上传 |
| | `POST /api/kb/delete` | 批量删除 |
| | `POST /api/kb/reclassify` | 调整分类 |
| 向量库 | `POST /api/vector/build` | 启动入库任务 |
| | `GET /api/vector/progress` | 入库进度 |
| | `POST /api/vector/reset` | 清空向量库 |
| | `POST /api/vector/search` | 检索调试 |
| 历史 | `POST /api/history/list` | 条件查询 |
| | `GET /api/history/stats` | 基础统计 |
| | `GET /api/history/export` | 导出 CSV |
| 设置 | `GET/POST /api/settings` | 读取/保存配置 |
| | `POST /api/settings/test` | 模型连通性测试 |
| Agent | `GET /api/agent/tools` | 工具清单 |
| | `POST /api/agent/ask` | Agent 问答（含工具轨迹） |

完整交互式文档：<http://127.0.0.1:8000/docs>

---

## 八、实现要点

**为什么用文件型 Chroma 而不是向量数据库服务**
文档明确要求「纯文件存储、无独立服务、无端口占用」。Chroma 以 embedded 模式运行，
数据落在 `backend/data/chroma/`，随项目复制即可迁移。

**为什么清洗放在切片之前**
PDF 与网页文本常带页眉页脚、导航、版权声明。若先切片再清洗，噪声会与正文混在同一片段里，
检索时被误召回。本项目按「加载 → 清洗去重 → 切片」顺序处理。

**Mock 模式的意义**
没有密钥时若直接报错，整条链路无法演示。Mock 嵌入用字符 bigram 哈希生成确定性向量，
能真实走完「入库 → 检索 → 排序 → 组装 Prompt」全流程，便于验收与答辩演示。

**Agent 与 RAG 的边界**
RAG 是固定管道：检索一次 → 生成一次。Agent 把检索变成「模型可选的动作」，
因此能处理「先查天气，再判断能不能打药，最后算用药量」这类需要多步组合的问题。
两者共用同一套知识库、记忆与记录模块，切换成本为零。

---

## 九、常见问题

**Q：启动后首页显示「前端尚未构建」**
执行 `cd frontend && npm install && npm run build`，刷新即可。

**Q：问答返回「知识库尚未初始化」**
到「向量库构建」页执行一次构建。语料目录为空时需先导入语料。

**Q：切换嵌入模型后检索报维度错误**
不同嵌入模型维度不同。切换后必须重新构建向量库（系统按 provider+维度自动隔离 collection）。

**Q：回答里没有农业知识，只有通用建议**
检查 `TOP_K` 是否过小、语料是否覆盖该作物。可在「向量库构建」页用检索调试查看命中情况。

**Q：如何彻底重置**
删除 `backend/data/chroma/`、`backend/data/records/` 后重启，或在页面执行「清空向量库」。

---

## 十、许可与数据来源

- 语料来源：中国农业农村信息网（www.agri.cn）公开农技栏目，仅用于教学与研究。
- 气象数据：Open-Meteo 公开接口（无需密钥）。
- 本项目为高校软件工程综合实习作品。

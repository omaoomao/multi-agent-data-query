# 高校招生与就业分析助手

基于 LangGraph 的**一主多从**多智能体架构，支持高校招生与就业数据查询、深度分析、联网搜索、数据可视化和长短期记忆系统。

## 架构设计

```
MultiAgentSystem (agent.py)
    └── MasterAgent（主智能体 - 意图识别 / 路由 / 协调 / 记忆）
            ├── SQLQueryAgent       （子智能体 - NL2SQL + 自动纠错）
            ├── DataAnalysisAgent   （子智能体 - 数据分析 + ECharts 可视化）
            ├── WebSearchAgent      （子智能体 - Tavily 联网搜索）
            └── AnswerSampleAgent   （子智能体 - 闲聊/工具调用）
```

### 意图路由（10 种）

| 意图 | 触发场景 | 调用链路 |
|------|---------|---------|
| `simple_answer` | 简单问候/确认（你好、谢谢） | 主智能体直接回答 |
| `answer_sample` | 闲聊、常识问答、通用问题 | AnswerSampleAgent |
| `sql_only` | 纯数据查询 | SQLQueryAgent |
| `analysis_only` | 深度分析已有数据 | DataAnalysisAgent |
| `sql_and_analysis` | 查询 + 深度分析 | SQL → Analysis |
| `web_search` | 联网搜索（需深度整理） | WebSearchAgent |
| `search_and_sql` | 校内外数据对比 | SQL + WebSearchAgent |
| `system_command` | 文件系统操作 | 主智能体执行命令 |
| `analysis_quick` | 快速分析已有数据（对比/排序） | 快速分析节点 |
| `search_quick` | 快速联网搜索即时信息 | WebSearchAgent |

## 数据库结构（7 张表）

`school_demo.db` 包含 7 张表，覆盖学生全生命周期：

```
students ──1:N──→ student_scores ←──N:1── courses ←──N:1── teachers
    │
    ├──1:N──→ internships
    │
    └──1:N──→ graduate_career

school_employment_stats（独立，按专业/年份统计招生就业）
```

| 表名 | 说明 | 数据量 |
|------|------|--------|
| `school_employment_stats` | 各专业招生就业统计 | CSV 导入 |
| `students` | 学生基本信息 | 500 条 |
| `teachers` | 教师信息 | 60 条 |
| `courses` | 课程目录 | 120 条 |
| `student_scores` | 学生成绩 | 3000 条 |
| `internships` | 实习记录 | 400 条 |
| `graduate_career` | 毕业生职业追踪 | 500 条 |

## 核心功能

### 1. NL2SQL 查询（SQLQueryAgent）

- Few-shot 提示词引导 LLM 生成 SQL
- **Reflection 自动纠错**：执行失败时将错误信息反馈 LLM 重新生成，最多重试 3 次
- 通过 **MCP 协议**调用独立 SQL 服务器执行查询，不可用时自动降级为直连 SQLite

### 2. 数据分析与可视化（DataAnalysisAgent）

- 文字洞察：自动统计数值字段（最小/最大/平均），生成分析报告
- **ECharts 可视化**：LLM 自动选择图表类型（bar / line / pie）并生成配置，前端直接渲染

### 3. 联网搜索（WebSearchAgent）

- **纯搜索模式**：调用 Tavily API 检索互联网信息，LLM 综合多来源内容生成回答
- **搜索+SQL 联合对比**：同时查询学校数据库与互联网，从两个维度对比分析
- **优雅降级**：未配置 `TAVILY_API_KEY` 时自动降级，不影响其他功能

### 4. 闲聊问答（AnswerSampleAgent）

- 处理与学校数据库无关的通用问题、闲聊、代码编写等
- 支持工具调用，可读写文件、执行命令
- 未初始化时自动降级为裸 LLM 调用

### 5. 三层记忆压缩策略

系统采用三层递进式压缩策略，支持长会话与大规模上下文：

**Layer 1 — 微压缩（每次调用执行，零成本）**
- 保留最近 6 个工具调用结果的完整内容
- 更早的 `tool_result` 被替换为 `[Previous: used xxx]` 占位符
- 无工具调用时回退为长消息截断（>500 字符截断为前 200 字 + ...）

**Layer 2 — 自动压缩（token 超限时执行，一次 LLM 调用）**
- 触发条件：消息数 > 11 且 token 估算超过 `short_term_max_tokens`
- 用 `deepcopy` 保存原始消息，将完整 transcript 写入 `.transcripts/` 目录
- 拆分消息：**前 N 条交给 LLM 总结（≤300 字），最近 6 条原样保留**
- 写回 checkpointer：`[摘要消息, msg15, msg16, ..., msg20]`

**Layer 3 — 手动压缩（模型主动请求）**
- LLM 在回复中返回 `[[COMPACT]]` 标记时，触发 Layer 2 压缩
- 压缩完成后重新调用 LLM 生成最终答案

### 6. 长期记忆系统（LongTermMemory）

- SQLite 持久化，跨会话保留用户偏好和知识
- 自动提取：对话 ≥ 6 条消息时触发 LLM 提取
- 意图识别时注入用户历史上下文，实现个性化回答
- **兜底日志**：意图识别失败时自动记录到 `intent_fallback_log` 表，用于后续优化
- FTS5 全文检索：支持对用户知识的语义搜索

存储结构（4 张表）：

| 表 | 用途 |
|---|---|
| `users` | 用户基本信息 |
| `user_preferences` | 用户偏好（键值对） |
| `user_knowledge` | 用户知识（分类 + 置信度） |
| `intent_fallback_log` | 意图识别兜底日志 |

### 7. 流式输出

支持 SSE（Server-Sent Events）实时推送：

| 事件类型 | 说明 |
|---------|------|
| `status` | 当前处理步骤描述 |
| `intent` | 识别出的意图标签 |
| `sql` | 生成的 SQL 语句 |
| `sources` | 搜索来源 URL 列表 |
| `chart` | ECharts 图表配置 JSON |
| `chunk` | 回答文字流片段 |
| `done` | 完成信号 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 设置 API 密钥

```bash
# 必需：DashScope API Key
# Windows PowerShell
$env:DASHSCOPE_API_KEY = "your_dashscope_key"

# Linux/Mac
export DASHSCOPE_API_KEY=your_dashscope_key

# 可选：Tavily 联网搜索
$env:TAVILY_API_KEY = "your_tavily_key"
```

> Tavily API Key 申请：[https://app.tavily.com](https://app.tavily.com)，免费套餐每月 1000 次请求。
> 也可在 `config/config.yaml` 的 `search.tavily_api_key` 字段直接填写。

### 3. 初始化数据库

```bash
python data/init_school_db.py          # 初始化高校演示数据库
python data/init_school_extra_tables.py # 初始化扩展表（学生/教师/课程/成绩/实习/就业）
python data/init_memory_db.py          # 初始化长期记忆数据库
```

### 4. 启动 Web 前端

```bash
# Windows
start_web.bat

# Linux/Mac
chmod +x start_web.sh
./start_web.sh
```

浏览器访问：`http://localhost:5000`

### 5. 命令行模式

```bash
python agent.py
```

系统提示输入用户 ID，同一 `user_id` 可跨会话保留个人偏好。

**特殊命令**：
- `new` — 开始新会话（清空短期记忆，保留长期记忆）
- `info` — 查看当前用户信息和偏好
- `exit/quit` — 退出系统

## 配置说明

编辑 `config/config.yaml`：

```yaml
llm:
  provider: "dashscope"
  model: "qwen-turbo-latest"
  api_key: "${DASHSCOPE_API_KEY}"
  temperature: 0.1
  max_tokens: 2048

database:
  path: "./data/school_demo.db"

nl2sql:
  num_examples: 3          # Few-shot 示例数量

memory:
  long_term_db: "./data/long_term_memory.db"
  short_term_max_tokens: 1000    # Layer 2 触发阈值
  compression_threshold: 10
  auto_extract_knowledge: true   # 自动提取用户知识

search:
  tavily_api_key: "${TAVILY_API_KEY}"
  max_results: 5

mcp:
  enabled: true            # 启用 MCP SQL 服务器（false 则直连 SQLite）
  server_timeout: 30
```

## REST API

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 返回前端页面 |
| `/api/login` | POST | 用户登录，返回长期记忆偏好和知识 |
| `/api/query` | POST | 阻塞式查询 |
| `/api/query_stream` | POST | 流式 SSE 查询（推荐） |
| `/api/new_session` | POST | 新建会话 |
| `/api/user_info` | POST | 获取用户信息和知识列表 |
| `/api/health` | GET | 健康检查，返回搜索功能可用状态 |

## 使用示例

以下展示不同意图类型的实际对话流程，帮助理解系统如何路由和处理。

---

### 示例 1：简单问候（simple_answer）

```
用户：你好

系统：
  [意图识别] simple_answer
  [状态] 正在生成回答...

助手：你好！我是高校招生与就业分析助手，可以帮你查询学校数据、分析就业趋势、
     联网搜索信息等。有什么可以帮你的吗？
```

---

### 示例 2：数据查询（sql_only）

```
用户：软件工程专业2024年招了多少人？

系统：
  [意图识别] sql_only
  [状态] 正在查询数据库...
  [SQL] SELECT major, admitted FROM school_employment_stats
        WHERE major = '软件工程' AND year = 2024

助手：根据查询结果，软件工程专业 2024 年招收了 280 人。
```

---

### 示例 3：查询 + 深度分析（sql_and_analysis）

```
用户：分析一下各专业的就业情况

系统：
  [意图识别] sql_and_analysis
  [状态] 正在查询数据库...
  [SQL] SELECT major, employment_rate, avg_starting_salary_yuan
        FROM school_employment_stats WHERE year = 2024
  [状态] 正在分析数据...
  [图表] 柱状图：各专业就业率对比

助手：📊 2024 年各专业就业情况分析

     **关键发现：**
     1. 就业率 TOP 3：软件工程(96.2%)、人工智能(95.8%)、计算机科学(94.5%)
     2. 平均起薪最高：人工智能专业 ¥12,800/月
     3. 就业率最低：护理学(88.3%)，但就业稳定性最强

     **趋势分析：**
     工科类专业整体就业率高于文科，人工智能方向薪资增长最快...
```

---

### 示例 4：快速分析已有数据（analysis_quick）

```
用户：刚才查的软件工程和计算机科学的数据，帮我按就业率排序

系统：
  [意图识别] analysis_quick
  [状态] 正在快速分析...

助手：根据之前查询的数据，按就业率从高到低排序：

     | 专业 | 就业率 | 平均起薪 |
     |------|--------|---------|
     | 软件工程 | 96.2% | ¥11,500 |
     | 计算机科学 | 94.5% | ¥10,800 |

     软件工程就业率高出 1.7 个百分点，起薪也高出 ¥700。
```

---

### 示例 5：联网搜索（web_search）

```
用户：2025年人工智能行业的平均薪资是多少？

系统：
  [意图识别] web_search
  [状态] 正在搜索...
  [来源] 来源1: 2025年AI行业薪酬报告 - 某招聘平台
         来源2: 人工智能岗位薪资趋势 - 某科技媒体

助手：根据 2025 年最新数据，人工智能行业的平均薪资情况如下：

     - 初级 AI 工程师：¥15,000-25,000/月
     - 中级算法工程师：¥25,000-40,000/月
     - 高级 AI 架构师：¥40,000-80,000/月

     来源：某招聘平台 2025 年薪酬报告
```

---

### 示例 6：搜索 + SQL 联合对比（search_and_sql）

```
用户：我们学校人工智能专业就业率和行业平均水平相比怎么样？

系统：
  [意图识别] search_and_sql
  [状态] 正在查询数据库...
  [SQL] SELECT major, employment_rate FROM school_employment_stats
        WHERE major = '人工智能' AND year = 2024
  [状态] 正在搜索...
  [来源] 来源1: 2024年AI行业就业白皮书
  [状态] 正在分析数据...

助手：📊 人工智能专业校内外数据对比

     **校内数据：** 就业率 95.8%
     **行业平均：** 就业率 92.3%（2024年AI行业白皮书）

     **对比结论：**
     ✅ 我校人工智能专业就业率高于行业平均水平 3.5 个百分点
     ✅ 在同类院校中处于领先位置
     ⚠️ 行业竞争加剧，建议关注大模型方向技能培养
```

---

### 示例 7：闲聊问答（answer_sample）

```
用户：帮我写一个 Python 快速排序

系统：
  [意图识别] answer_sample
  [状态] 正在生成回答...

助手：好的，这是一个 Python 快速排序实现：

     ```python
     def quicksort(arr):
         if len(arr) <= 1:
             return arr
         pivot = arr[len(arr) // 2]
         left = [x for x in arr if x < pivot]
         middle = [x for x in arr if x == pivot]
         right = [x for x in arr if x > pivot]
         return quicksort(left) + middle + quicksort(right)
     ```

     时间复杂度：平均 O(n log n)，最坏 O(n²)
```

---

### 示例 8：系统命令（system_command）

```
用户：列出当前目录下的文件

系统：
  [意图识别] system_command
  [状态] 正在执行系统命令...

助手：当前目录下的文件和文件夹：

     📁 agents/
     📁 config/
     📁 data/
     📁 memory/
     📁 static/
     📁 tests/
     📄 agent.py
     📄 app.py
     📄 prompts.py
     📄 requirements.txt
     ...
```

---

### 示例 9：多轮对话 + 记忆

```
第一轮：
  用户：软件工程专业就业率多少？
  助手：2024年软件工程专业就业率为 96.2%。

第二轮：
  用户：那计算机科学呢？
  助手：2024年计算机科学与技术专业就业率为 94.5%。
       （系统从短期记忆中获取了上一轮查询的上下文）

第三轮：
  用户：帮我对比一下这两个专业
  系统：[意图识别] analysis_quick（使用已有数据，不重新查询）
  助手：软件工程就业率高出 1.7 个百分点...
```

---

### 快速测试清单

| 场景 | 示例问题 |
|------|---------|
| 问候 | 你好 |
| 闲聊 | 帮我写一段 Python 代码 |
| 简单查询 | 软件工程专业招了多少人？ |
| 跨表查询 | 哪个学生的 GPA 最高？ |
| 深度分析 | 分析各专业就业水平并给出建议 |
| 快速分析 | 对比一下刚才的数据 |
| 联网搜索 | Python 最新版有什么新特性？ |
| 联合对比 | 我校就业率和行业比怎么样？ |
| 文件操作 | 读取 config.yaml 的内容 |
| 多轮对话 | 先问就业率，再问"那XX专业呢？"，再问"帮我对比" |

## 目录结构

```
Multi-Agent-Exp-main/
├── agents/                          # 智能体模块
│   ├── __init__.py
│   ├── master_agent.py             # 主智能体（意图识别 / 路由 / 记忆 / 汇总）
│   ├── sql_agent.py                # SQL 查询子智能体（含自动纠错）
│   ├── analysis_agent.py           # 数据分析子智能体（含 ECharts）
│   ├── search_agent.py             # 联网搜索子智能体（Tavily）
│   ├── answer_sample_agent.py      # 闲聊/工具调用子智能体
│   ├── tools.py                    # LangChain 工具定义
│   ├── mcp_client.py               # MCP SQL 客户端封装
│   ├── skill_loader.py             # 技能加载器
│   └── _utils.py                   # 共享工具函数
├── memory/                          # 记忆模块
│   ├── long_term_memory.py         # 长期记忆管理器（SQLite + FTS5）
│   └── memory_extractor.py         # 记忆提取器（LLM 自动提取）
├── data/                            # 数据模块
│   ├── school_demo.db              # 高校演示数据库（7 张表）
│   ├── long_term_memory.db         # 长期记忆数据库（4 张表）
│   ├── init_school_db.py           # 高校数据库初始化
│   ├── init_school_extra_tables.py # 扩展表初始化（学生/教师/课程等）
│   ├── init_memory_db.py           # 记忆数据库初始化
│   └── school_demo_employment_data.csv  # 招生就业原始数据
├── config/
│   └── config.yaml                 # 配置文件
├── static/                          # Web 前端
│   ├── index.html                  # 主页面
│   ├── style.css                   # 样式
│   └── app.js                      # 前端逻辑（SSE / ECharts）
├── skills/                          # 技能定义
├── tests/                           # 测试
├── agent.py                         # 主入口（MultiAgentSystem 类）
├── app.py                           # Flask Web API 服务
├── prompts.py                       # 提示词定义
├── mcp_sql_server.py                # MCP SQL 服务器
├── start_web.bat                    # Windows 启动脚本
├── start_web.sh                     # Linux/Mac 启动脚本
└── requirements.txt                 # Python 依赖
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 工作流编排 | LangGraph |
| LLM 框架 | LangChain |
| 大语言模型 | 通义千问（qwen-turbo-latest） |
| 联网搜索 | Tavily（langchain-tavily） |
| 数据库协议 | MCP（Model Context Protocol） |
| 数据存储 | SQLite + FTS5 全文检索 |
| Web 框架 | Flask + Flask-CORS |
| 前端可视化 | ECharts、marked.js、highlight.js |
| 终端美化 | Rich |

## 注意事项

- 必须设置 `DASHSCOPE_API_KEY` 环境变量
- 联网搜索需额外设置 `TAVILY_API_KEY`（不配置不影响其他功能）
- 初次运行前需执行数据库初始化脚本
- 使用相同的 `user_id` 可跨会话保留个人偏好
- 长期记忆数据库建议定期备份（`data/long_term_memory.db`）

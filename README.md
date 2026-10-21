# 社群决策 AI（第一版）

上传一段群聊对话 → 意图分析 → 多智能体协作 → 输出决策报告。

一条完整、可运行的流程：

```
输入 TXT/JSON 对话文件 → 解析消息 → 意图分析智能体 → 三位评审智能体（两轮协作）→ 决策主持人 → 决策报告
```

- 前端：原生 HTML / CSS / JavaScript（无构建步骤）
- 后端：Python + FastAPI
- AI 模型：DeepSeek 兼容 Chat Completions 接口
- 数据存储：JSON 文件（`data/sessions/<id>.json`）
- 多智能体：Python 自定义协调器（`backend/coordinator.py`）

## 目录结构

```
06群聊/
├── backend/
│   ├── main.py          # FastAPI 入口：上传、流水线、查询、静态页面
│   ├── config.py        # 环境变量 / .env 配置
│   ├── parser.py        # TXT / JSON 对话文件解析
│   ├── llm.py           # DeepSeek 兼容 LLM 客户端（含离线演示模式）
│   ├── coordinator.py   # 自定义多智能体协调器 + 提示词
│   ├── pipeline.py      # 后台流水线（进度写回会话文件）
│   ├── storage.py       # JSON 文件存储（原子写入）
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── samples/             # 示例对话文件
├── data/sessions/       # 运行时生成的会话数据
├── .env.example
└── README.md
```

## 快速开始

要求：Python 3.10+。

```bash
# 1. 安装依赖
cd 06群聊
python -m venv .venv
.venv\Scripts\activate        # Windows（macOS/Linux: source .venv/bin/activate）
pip install -r backend/requirements.txt

# 2. 配置模型（将 .env.example 复制为 .env，填入 API Key）
copy .env.example .env        # Windows
# 编辑 .env：LLM_API_KEY=sk-xxxx

# 3. 启动服务
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

浏览器打开 <http://127.0.0.1:8000>，在左侧上传 `samples/示例对话-读书会.txt` 或
`samples/示例对话-羽毛球活动.json`，点击「开始分析」。

### 离线演示模式

没有 API Key 或暂时无法联网时，在 `backend` 目录下设置环境变量后启动：

```bash
# Windows PowerShell
$env:LLM_MOCK="1"
python -m uvicorn main:app --port 8000
```

页面右上角会显示「离线演示模式」：对话解析、任务流水线、报告渲染与存储都是真实执行的，
只有模型输出使用内置演示数据，用于在无网络环境验证完整流程。**正式使用请配置真实 API Key。**

## 支持的对话文件格式

### TXT

每行一条消息，格式为 `昵称: 内容`，也支持带时间前缀：

```
林小雨: 下周读书会选题想听听大家的意见。
[2024-05-12 20:01:33] 陈默: 我投《置身事内》。
2024-05-12 20:05:00 王浩: 赞同陈默。
```

- 无发言人前缀的续行会拼接到上一条消息（支持多行消息）
- 微信导出风格 `昵称 12:30`（时间在行尾、内容在下一行）也能识别

### JSON

支持消息数组，或包含 `messages` / `conversation` / `data` 数组的对象：

```json
[
  { "speaker": "阿杰", "content": "下个月改成固定周二晚上打双打？" },
  { "speaker": "雨桐", "content": "周二晚我可以。" }
]
```

字段兼容：发言人 `speaker/name/user/from/author`，内容 `content/text/message/msg`，时间 `time/timestamp`。
另支持逐行 JSON（JSONL）。

## 流程说明

1. **解析**：上传文件 → 统一为 `{speaker, content, time}` 消息列表
2. **意图分析**：意图分析智能体提炼讨论主题、核心决策问题、各方立场、共识与分歧
3. **多智能体协作**（自定义协调器，两轮）：
   - 第一轮：务实派 / 风险派 / 共情派三位智能体基于对话与意图分析**并行**独立发表意见
   - 第二轮：每位智能体阅读其他人第一轮意见后**并行**修订立场，输出认同点与保留意见
4. **决策报告**：决策主持人综合意图分析与两轮意见，输出标题、背景、共识、分歧、最终决策、
   依据、风险、行动清单与置信度

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 服务与模型状态 |
| POST | `/api/sessions?filename=xx.txt` | 上传对话文件（也支持 `multipart/form-data`），返回解析结果 |
| POST | `/api/sessions/{id}/run` | 启动决策流水线（后台执行） |
| GET | `/api/sessions/{id}` | 查询会话（含进度、意图、智能体意见、报告） |
| GET | `/api/sessions` | 会话列表 |
| DELETE | `/api/sessions/{id}` | 删除会话 |

前端每 1.5 秒轮询 `GET /api/sessions/{id}` 更新进度与结果。

## 配置项

| 环境变量 | 说明 | 默认 |
| --- | --- | --- |
| `LLM_API_KEY` | 大模型 API Key（也可用 `DEEPSEEK_API_KEY`） | 空 |
| `LLM_BASE_URL` | Chat Completions 地址前缀（DeepSeek 兼容） | `https://api.deepseek.com` |
| `LLM_MODEL` | 模型名称 | `deepseek-chat` |
| `LLM_TIMEOUT` | 单次请求超时（秒） | `120` |
| `LLM_MOCK` | `1` 启用离线演示模式 | `0` |

## 说明与边界（第一版）

- 数据保存为 `data/sessions/<id>.json`，原子写入；上传文件上限 2MB，单次分析约 8 次模型调用
- 单次对话送给模型前会按字符数截断（约 16000 字符），避免超长上下文
- 流水线在进程内后台线程执行，进度通过会话文件持久化；服务重启不会恢复聊天状态，需重新分析
- 本版不做登录、鉴权、多租户，仅面向本机使用

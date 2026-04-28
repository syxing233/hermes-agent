# Hermes Agent 可调用接口文档

本文档整理外部系统可以调用 Hermes Agent 的主要入口。

Hermes 不是“所有能力都只有一个 API 接口”。核心是 `AIAgent` Python 类，
外层再通过 HTTP API、Webhook、MCP、ACP、消息平台和 Web UI 后端暴露不同入口。

## 总览

| 入口 | 协议 | 主要用途 | 默认端口 |
| --- | --- | --- | --- |
| `AIAgent` Python 类 | 进程内 Python | 在 Python 代码里直接嵌入 Hermes | 无 |
| Gateway API Server | HTTP，OpenAI 兼容 | 外部系统调用 Agent 的主接口 | `8642` |
| Gateway Webhook Adapter | HTTP Webhook | 外部事件触发 Agent 运行 | `8644` |
| Web UI Backend | HTTP + WebSocket | Dashboard、配置、会话、代理 Gateway API | `8648` |
| MCP Server | MCP over stdio | 给 MCP 客户端暴露消息和会话桥接工具 | 无 |
| ACP Adapter | Agent Client Protocol | VS Code / Zed / JetBrains 等编辑器集成 | 无 |
| 消息平台适配器 | 平台 API/Webhook/WebSocket | Telegram、Discord、Slack、飞书、企微等 | 各平台不同 |
| 合规检测独立 API | FastAPI | 独立合规检测服务 | `8000` |

## 核心 Python API

源码：`run_agent.py`

适合在 Python 代码里直接调用 Hermes。

示例：

```python
from run_agent import AIAgent

agent = AIAgent(model="anthropic/claude-opus-4.6")
answer = agent.chat("Hello")
```

主要方法：

| 方法 | 说明 |
| --- | --- |
| `AIAgent.chat(message)` | 简单调用，返回最终回答字符串 |
| `AIAgent.run_conversation(...)` | 完整调用，返回包含 `final_response` 和消息列表的 dict |

`run_conversation` 支持自定义 `system_message`、历史消息、`task_id`、
流式回调和持久化控制。

## Gateway API Server

源码：`gateway/platforms/api_server.py`

这是外部系统调用 Hermes Agent 最推荐的 HTTP 接口层。它暴露 OpenAI 兼容接口，
同时提供 Hermes 自有的运行事件流和定时任务管理接口。

### 启用方式

在 `${HERMES_HOME}/.env` 中配置：

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=change-me-local-dev
# 可选
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
API_SERVER_CORS_ORIGINS=http://localhost:3000
API_SERVER_MODEL_NAME=hermes-agent
```

启动 Gateway：

```bash
source venv/bin/activate
hermes gateway run
```

安全注意事项：

- 默认只监听 `127.0.0.1`。
- 如果绑定 `0.0.0.0`，必须配置 `API_SERVER_KEY`。
- 请求使用 `Authorization: Bearer <API_SERVER_KEY>` 鉴权。
- 该接口能调用完整 Agent 工具集；启用相关工具时包括终端、文件操作等能力。

### 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 基础健康检查 |
| `GET` | `/health/detailed` | 给 Dashboard 使用的详细状态 |
| `GET` | `/v1/health` | OpenAI 风格健康检查 |
| `GET` | `/v1/models` | 返回 Hermes 暴露的模型名 |
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions 格式 |
| `POST` | `/v1/responses` | OpenAI Responses 格式，支持响应链上下文 |
| `GET` | `/v1/responses/{response_id}` | 获取已保存的 response |
| `DELETE` | `/v1/responses/{response_id}` | 删除已保存的 response |
| `POST` | `/v1/runs` | 启动 Agent run，立即返回 `run_id` |
| `GET` | `/v1/runs/{run_id}/events` | run 的 SSE 结构化事件流 |
| `GET` | `/api/jobs` | 查询 cron jobs |
| `POST` | `/api/jobs` | 创建 cron job |
| `GET` | `/api/jobs/{job_id}` | 查询单个 cron job |
| `PATCH` | `/api/jobs/{job_id}` | 更新 cron job |
| `DELETE` | `/api/jobs/{job_id}` | 删除 cron job |
| `POST` | `/api/jobs/{job_id}/pause` | 暂停 cron job |
| `POST` | `/api/jobs/{job_id}/resume` | 恢复 cron job |
| `POST` | `/api/jobs/{job_id}/run` | 立即触发 cron job |

### `POST /v1/chat/completions`

无状态 OpenAI Chat Completions 请求。调用方需要传完整消息历史。

```bash
curl http://127.0.0.1:8642/v1/chat/completions \
  -H "Authorization: Bearer change-me-local-dev" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes-agent",
    "messages": [
      {"role": "user", "content": "List the files in this project"}
    ],
    "stream": false
  }'
```

设置 `"stream": true` 后返回流式响应。流中使用 OpenAI chat chunk，
并可能包含 Hermes 自定义工具进度事件。

### `POST /v1/responses`

OpenAI Responses 风格接口。可通过 `previous_response_id` 或命名
`conversation` 维护服务端上下文。

请求示例：

```json
{
  "model": "hermes-agent",
  "input": "What files are in this project?",
  "instructions": "Be concise.",
  "store": true
}
```

通过 response ID 继续：

```json
{
  "input": "Now open the README",
  "previous_response_id": "resp_abc123"
}
```

通过命名会话继续：

```json
{"conversation": "my-project", "input": "Hello"}
{"conversation": "my-project", "input": "Run the tests"}
```

### `POST /v1/runs`

适合“先拿 run ID，再单独消费事件流”的调用方。

调用流程：

1. `POST /v1/runs`
2. 读取返回的 `run_id`
3. 连接 `GET /v1/runs/{run_id}/events`

事件接口返回 Server-Sent Events。

## Generic Webhook Adapter

源码：`gateway/platforms/webhook.py`

用于让 GitHub、GitLab、Jira、Stripe、CI/CD 等外部系统推送事件给 Hermes。
Webhook Adapter 会验证 HMAC 签名，将 payload 转成 Agent prompt，并可把最终
响应投递到另一个目标。

环境变量启用示例：

```bash
WEBHOOK_ENABLED=true
WEBHOOK_PORT=8644
WEBHOOK_SECRET=your-secret
```

接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `POST` | `/webhooks/{route_name}` | 接收某个配置路由的 webhook 事件 |

Webhook 路由配置来自 `platforms.webhook.extra.routes`，也可以通过
`hermes webhook subscribe` 创建动态订阅。

每个路由可配置：

- 允许的事件类型
- HMAC secret
- prompt 模板
- 可选 skills
- 响应投递目标
- 投递附加参数

## Web UI Backend API

源码：`hermes-web-ui/packages/server/src/routes`

这是 Hermes Dashboard 的后端接口层，负责 profile、session、配置、provider、
skill、日志、gateway、上传和浏览器终端等管理能力。它也会代理部分请求到
Gateway API Server。

默认开发端口：`8648`

OpenAPI 文档文件：

```text
hermes-web-ui/docs/openapi.json
```

主要接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | Web UI 后端健康检查 |
| `POST` | `/upload` | 上传文件 |
| `POST` | `/webhook` | Web UI webhook 接收口 |
| `GET` | `/api/hermes/sessions` | 查询 sessions |
| `GET` | `/api/hermes/sessions/{id}` | 查询 session 详情 |
| `DELETE` | `/api/hermes/sessions/{id}` | 删除 session |
| `POST` | `/api/hermes/sessions/{id}/rename` | 重命名 session |
| `GET` | `/api/hermes/config` | 读取 Hermes 配置 |
| `PUT` | `/api/hermes/config` | 更新 Hermes 配置 |
| `PUT` | `/api/hermes/config/credentials` | 保存平台凭证 |
| `GET` | `/api/hermes/available-models` | 获取可用模型 |
| `GET` | `/api/hermes/config/models` | 读取模型配置 |
| `PUT` | `/api/hermes/config/model` | 更新默认模型 |
| `POST` | `/api/hermes/config/providers` | 新增 provider |
| `PUT` | `/api/hermes/config/providers/{poolKey}` | 更新 provider |
| `DELETE` | `/api/hermes/config/providers/{poolKey}` | 删除 provider |
| `GET` | `/api/hermes/skills` | 查询 skills |
| `PUT` | `/api/hermes/skills/toggle` | 启用或禁用 skill |
| `GET` | `/api/hermes/memory` | 读取 memory |
| `POST` | `/api/hermes/memory` | 保存 memory |
| `GET` | `/api/hermes/profiles` | 查询 profiles |
| `POST` | `/api/hermes/profiles` | 创建 profile |
| `PUT` | `/api/hermes/profiles/active` | 切换活跃 profile |
| `GET` | `/api/hermes/gateways` | 查询 gateway 状态 |
| `POST` | `/api/hermes/gateways/{name}/start` | 启动 gateway 平台 |
| `POST` | `/api/hermes/gateways/{name}/stop` | 停止 gateway 平台 |
| `GET` | `/api/hermes/logs` | 查询日志列表 |
| `GET` | `/api/hermes/logs/{name}` | 读取日志 |
| `GET` | `/api/hermes/weixin/qrcode` | 获取微信登录二维码 |
| `GET` | `/api/hermes/weixin/qrcode/status` | 查询微信扫码状态 |
| `POST` | `/api/hermes/weixin/save` | 保存微信凭证 |
| `POST` | `/api/hermes/compliance-review` | Web UI 合规审查辅助接口 |
| `POST` | `/api/hermes/vision-analyze` | Web UI 视觉分析辅助接口 |
| `WS` | `/api/hermes/terminal` | 浏览器终端 WebSocket |
| `ALL` | `/api/hermes/v1/{path}` | 代理到上游 `/v1/{path}` |
| `ALL` | `/api/hermes/{path}` | 代理到上游 `/api/{path}` |

受保护路由由 Web UI 后端统一鉴权。

## MCP Server

源码：`mcp_serve.py`

这是给 Claude Code、Cursor、Codex 等 MCP 客户端使用的 stdio MCP server，
不是 HTTP API。

启动：

```bash
hermes mcp serve
```

MCP 客户端配置示例：

```json
{
  "mcpServers": {
    "hermes": {
      "command": "hermes",
      "args": ["mcp", "serve"]
    }
  }
}
```

暴露的 MCP tools：

| Tool | 说明 |
| --- | --- |
| `conversations_list` | 查询活跃消息会话 |
| `conversation_get` | 按 session key 查询单个会话 |
| `messages_read` | 读取消息历史 |
| `attachments_fetch` | 获取附件元数据或内容引用 |
| `events_poll` | 轮询会话事件 |
| `events_wait` | 长轮询等待下一条会话事件 |
| `messages_send` | 向平台会话发送消息 |
| `channels_list` | 查询可发送的消息目标 |
| `permissions_list_open` | 查询当前 bridge 看到的待审批请求 |
| `permissions_respond` | 批准或拒绝待审批请求 |

## ACP Adapter

源码：`acp_adapter/server.py`

ACP Adapter 通过 Agent Client Protocol 暴露 Hermes，主要服务编辑器/IDE 集成。
它不是普通 REST API。能力包括 session 管理、slash commands、工具进度事件，
以及注册 ACP 客户端提供的 MCP servers。

典型调用方：VS Code、Zed、JetBrains 等支持 ACP 的客户端。

## 消息平台适配器

源码目录：`gateway/platforms/`

这些平台不是共用一个 REST API，而是各自使用平台协议：

- Telegram：Bot API polling 或 webhook mode
- Discord：Discord gateway/events
- Slack：Slack APIs/events
- 飞书/Lark：websocket 或 webhook mode
- 企微、微信、QQ Bot、Matrix、Mattermost、Signal、SMS、Email、Home Assistant、
  BlueBubbles 等均有各自适配器

所有平台消息最终都会进入 Gateway，由 Gateway 创建或恢复 Hermes session，
再调用 `AIAgent`。

## Agent 内的合规工具集

源码：`tools/compliance_tool.py`

合规检测在 Hermes Agent 内部是一个 `compliance` toolset。当前公开给 Agent
选择的工具有 3 个：

| 工具 | 说明 |
| --- | --- |
| `compliance_health` | 检查内嵌合规引擎配置和 artifact store 状态 |
| `compliance_review` | 核心检测工具，处理文件/文本、材料类型、外部 workflow 调用和报告落盘 |
| `compliance_get_report` | 按 `review_id` 或 artifact 路径读取已保存报告 |

旧的 `compliance_assistant` 兼容函数仍保留在代码里，供旧代码直接 import 时使用，
但不再注册为 Agent 可见工具，也不再出现在 `compliance` toolset 中。新流程应直接
使用 `compliance_review`。

## 合规检测独立 API

源码：`compliance_agent/standalone/api_app.py`

这是独立的 FastAPI 合规检测服务，详细文档见：

```text
docs/compliance-detection-api.md
```

默认端口：`8000`

主要接口：

- `POST /v1/assistant`
- `POST /v1/assistant/stream`
- `POST /v1/review/ingest`
- `POST /v1/review/ingest/stream`

## 选择哪个入口

| 需求 | 推荐入口 |
| --- | --- |
| 外部系统通用调用 Agent | Gateway API Server 的 `/v1/chat/completions` 或 `/v1/responses` |
| OpenAI 兼容前端接入 | Gateway API Server，地址 `http://host:8642/v1` |
| 需要 run ID 和结构化事件流 | Gateway `/v1/runs` + `/v1/runs/{run_id}/events` |
| 外部事件触发 Agent | Webhook Adapter `/webhooks/{route_name}` |
| Dashboard / 管理端 | Web UI Backend |
| IDE / 编辑器 Agent 集成 | ACP Adapter |
| MCP 客户端集成 | `hermes mcp serve` |
| 独立合规审查服务 | 合规 FastAPI `/v1/review/ingest` |
| Python 代码内直接调用 | `AIAgent.chat()` 或 `AIAgent.run_conversation()` |

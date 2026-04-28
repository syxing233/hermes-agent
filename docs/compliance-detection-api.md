# 合规检测独立 API 文档

本文档整理 `compliance_agent/standalone/api_app.py` 中定义的独立
FastAPI 服务接口。

## 定位

这是一个独立的合规检测 HTTP 服务，能力包括：

- 对文本或上传文件执行合规检测。
- `material_type` 留空时自动识别材料类型。
- 通过 SSE 流式返回检测进度、检测项和报告解读。
- 为独立助手接口保存轻量会话历史。

注意：Hermes 主 Agent 运行时的默认路径不是通过这个 HTTP 服务调用合规检测，
而是在进程内通过 `compliance_review` 工具直接调用 `compliance_agent` 包。

## 启动方式

推荐本地启动命令：

```bash
source venv/bin/activate
uvicorn compliance_agent.standalone.api_app:app --host 0.0.0.0 --port 8000
```

启动后可访问 FastAPI 自动文档：

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/openapi.json`

## 支持的材料类型

`material_type` 支持：

- `合同`
- `条款书`
- `产品说明书`
- `营销物料`
- `海报`

在 `/v1/review/ingest` 和 `/v1/review/ingest/stream` 中，
不传 `material_type` 会触发自动分类。

## 接口总览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `POST` | `/v1/conversations` | 创建独立会话 |
| `GET` | `/v1/conversations` | 查询会话列表 |
| `GET` | `/v1/conversations/{conversation_id}/messages` | 查询会话消息 |
| `DELETE` | `/v1/conversations/{conversation_id}` | 删除会话 |
| `POST` | `/v1/review` | 旧版单次审查接口，已标记 deprecated |
| `POST` | `/v1/assistant` | 助手接口，自动判断聊天或检测 |
| `POST` | `/v1/assistant/stream` | 助手 SSE 流式接口 |
| `POST` | `/v1/review/ingest` | 文件/文本合规检测 |
| `POST` | `/v1/review/ingest/stream` | 文件/文本合规检测 SSE 流式接口 |

## 健康检查

### `GET /health`

返回服务状态和版本信息。

示例响应：

```json
{
  "ok": true,
  "service": "compliance-agent",
  "version": "0.0.0",
  "build": ""
}
```

## 会话接口

### `POST /v1/conversations`

创建一个独立会话，用于 `/v1/assistant` 或 `/v1/review/ingest` 追加历史。

请求体：

```json
{
  "user": "anonymous",
  "title": "合同审查"
}
```

响应：

```json
{
  "conversation_id": "conv_xxx",
  "user": "anonymous",
  "title": "合同审查",
  "created_at": "2026-04-28T00:00:00Z",
  "updated_at": "2026-04-28T00:00:00Z",
  "last_message_at": "2026-04-28T00:00:00Z"
}
```

### `GET /v1/conversations`

查询参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `user` | `anonymous` | 会话所属用户 |
| `limit` | `50` | 范围 `1..200` |
| `offset` | `0` | 分页偏移 |

### `GET /v1/conversations/{conversation_id}/messages`

查询参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `user` | `anonymous` | 会话所属用户 |
| `limit` | `200` | 范围 `1..500` |

### `DELETE /v1/conversations/{conversation_id}`

查询参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `user` | `anonymous` | 会话所属用户 |

删除成功返回：

```json
{"ok": true}
```

## 助手接口

### `POST /v1/assistant`

适合需要“先理解用户意图，再决定聊天或合规检测”的调用方。

请求体：

```json
{
  "user": "anonymous",
  "message": "请审查这段营销物料",
  "input_text": "这里放待审查文本",
  "material_type": "营销物料",
  "conversation_id": null,
  "history": []
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `user` | 否 | 默认 `anonymous` |
| `message` | 否 | 用户指令 |
| `input_text` | 否 | 待审查文本 |
| `input_file` | 否 | 本地文件描述对象，见下方 schema |
| `material_type` | 否 | 支持的材料类型之一；可留空 |
| `conversation_id` | 否 | 绑定到某个独立会话 |
| `history` | 否 | 聊天历史，格式为 `{role, content}` 数组 |

响应结构：

```json
{
  "mode": "detection",
  "reply": "已完成合规检测...",
  "intent": {
    "mode": "detection",
    "reason": "",
    "confidence": 0.0,
    "material_type": "营销物料",
    "requested_material_type": "营销物料"
  },
  "conversation_id": "conv_xxx",
  "report": {
    "task_id": "task_xxx",
    "source_count": 1,
    "summary": {
      "risk_count": 1,
      "no_risk_count": 0,
      "total_items": 1,
      "supported_count": 1,
      "unsupported_count": 0
    },
    "reports": []
  }
}
```

### `POST /v1/assistant/stream`

请求体同 `/v1/assistant`。

响应类型：`text/event-stream`

事件类型：

| 事件 | 说明 |
| --- | --- |
| `status` | 当前处理阶段 |
| `report_item` | 增量合规检测项 |
| `analysis_chunk` | 报告解读文本增量 |
| `chat_chunk` | 普通聊天回复文本增量 |
| `result` | 最终 `AssistantResponse` |
| `error` | 错误信息 |
| `done` | 流结束 |

SSE 数据格式：

```text
event: status
data: {"stage":"输入编排层","detail":"...","operation":"analyzing"}
```

## 文件/文本检测接口

### `POST /v1/review/ingest`

适合直接对文件或文本做合规检测。

请求类型：`multipart/form-data`

表单字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `files` | 否 | 一个或多个上传文件 |
| `text` | 否 | 文本输入；无文件时必须提供非空文本 |
| `text_as_source` | 否 | 兼容字段；有文件时文本不会作为额外检测源 |
| `material_type` | 否 | 留空自动分类 |
| `user` | 否 | 默认 `anonymous` |
| `conversation_id` | 否 | 已存在的会话 ID，用于追加历史 |

至少需要传一个文件或非空 `text`。

文本示例：

```bash
curl http://127.0.0.1:8000/v1/review/ingest \
  -F 'material_type=营销物料' \
  -F 'user=anonymous' \
  -F 'text=本产品收益稳定，承诺稳赚不赔。'
```

文件示例：

```bash
curl http://127.0.0.1:8000/v1/review/ingest \
  -F 'material_type=合同' \
  -F 'files=@/path/to/contract.pdf'
```

响应结构：

```json
{
  "task_id": "task_xxx",
  "source_count": 1,
  "summary": {
    "risk_count": 1,
    "no_risk_count": 2,
    "total_items": 3,
    "supported_count": 1,
    "unsupported_count": 0
  },
  "reports": [
    {
      "task_id": "task_xxx",
      "meta": {
        "skill_name": "marketing-material-compliance-check",
        "api_route": "general-compliance-workflow",
        "input_file": "",
        "material_type": "营销物料",
        "query": "",
        "source": "inline_text_1",
        "contract_type": ""
      },
      "summary": {
        "risk_count": 1,
        "no_risk_count": 2,
        "total_items": 3
      },
      "items": [
        {
          "check_title": "收益承诺",
          "result": "存在风险",
          "reason": "...",
          "source_excerpt": "...",
          "basis": "...",
          "suggestion": "..."
        }
      ],
      "supported": true,
      "needs_human_review": false
    }
  ],
  "analysis": {
    "summary_markdown": "...",
    "model": "",
    "based_on_items": 3,
    "generated_by_model": true
  }
}
```

### `POST /v1/review/ingest/stream`

表单字段同 `/v1/review/ingest`。

响应类型：`text/event-stream`

事件类型：

| 事件 | 说明 |
| --- | --- |
| `status` | 上传、分类、检测、报告生成状态 |
| `report_item` | 增量检测项和当前汇总 |
| `analysis_chunk` | 报告解读文本增量 |
| `report` | 最终 `BatchSkillReviewReport` |
| `error` | 错误信息 |
| `done` | 流结束 |

## 旧版审查接口

### `POST /v1/review`

该接口接收 JSON 格式的 `ComplianceRequest`，已经在 FastAPI 中标记为
deprecated。新调用方优先使用 `/v1/review/ingest`。

请求体：

```json
{
  "user": "anonymous",
  "query": "请检测这份合同",
  "material_type": "合同",
  "input_text": "合同文本",
  "contract_type": "通用",
  "statement": "甲方",
  "scale": "强势",
  "json_rules": [],
  "human_review_override": null,
  "extra": {}
}
```

## 通用 Schema

### `input_file`

用于 `/v1/assistant` 和 `/v1/review` 这类 JSON 请求体。

```json
{
  "type": "document",
  "transfer_method": "local_file",
  "upload_file_id": null,
  "local_path": "/absolute/path/to/file.pdf"
}
```

### `SkillCheckItem`

单条检测项结构：

```json
{
  "check_title": "",
  "result": "",
  "reason": "",
  "source_excerpt": "",
  "basis": "",
  "suggestion": ""
}
```

### `StatusEvent`

进度事件结构：

```json
{
  "at": "2026-04-28T00:00:00Z",
  "stage": "输入编排层",
  "detail": "start_source=1/1, source=inline_text_1",
  "operation": "analyzing"
}
```

## 错误行为

- `/v1/review/ingest` 未提供文件且 `text` 为空时返回 `400`。
- `material_type` 非法时返回 `400`。
- `conversation_id` 不存在或无权限时返回 `404`。
- 流式接口执行失败时会发送 `error` 事件，然后发送 `done` 事件结束。

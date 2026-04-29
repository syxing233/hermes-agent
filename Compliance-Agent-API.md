# Hermes 合规检测 Agent API 对接手册

本文面向内部测试同事、业务系统调用方、后续多 Agent 编排方。文档只描述 **合规检测 Agent + Hermes Agent 外壳** 这条调用链：请求进入 Hermes Gateway API Server，由 Hermes Agent 主循环加载 `compliance-cn` 人格、`compliance-specialist` toolset 和预加载的合规 skill 后执行。

**主推荐接口只有一个：`POST /v1/responses`。**  
多 Agent 联动、业务系统接入、普通单次合规审查，默认都使用该接口。其他接口仅用于兼容、长任务或运维。

## 1. 文档说明与安全提示

### 1.1 测试环境

测试环境通过 Web UI BFF 暴露，BFF 会把 `/v1/*` 转发到后端 Hermes Gateway API Server。

```bash
BASE_URL="http://js1.blockelite.cn:49505"
WEBUI_TOKEN="f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0"
REQUEST_ID="test-20260429-001"
```

本文 curl 示例全部写死完整地址、token 和 request id，方便直接复制测试。

### 1.2 安全提示

- 文档中的 `WEBUI_TOKEN` 仅用于内部测试环境。
- 不要把该 token 发布到公网仓库、外部文档、公开工单或聊天群。
- 如果文档需要外发，应先替换 token 为占位符。
- 如果 token 疑似泄露，应立即轮换。

### 1.3 通用请求头

业务调用建议都带上以下 header：

```http
Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0
X-Request-Id: test-20260429-001
Content-Type: application/json
```

字段说明：

| Header | 必填 | 说明 |
| --- | --- | --- |
| `Authorization` | 是 | Web UI BFF 鉴权 token |
| `X-Request-Id` | 建议 | 调用方生成的链路追踪 ID，便于排查问题 |
| `Content-Type` | POST JSON 必填 | 固定为 `application/json` |
| `Idempotency-Key` | 非流式 POST 建议 | 幂等键，重试同一请求时避免重复执行 |

`X-Request-Id` 和 `Idempotency-Key` 不同：

| 字段 | 作用 |
| --- | --- |
| `X-Request-Id` | 链路追踪，方便日志排查 |
| `Idempotency-Key` | 幂等控制，相同请求体和相同 key 可复用结果 |

### 1.4 路径规则

| 调用路径 | 说明 |
| --- | --- |
| `/v1/responses` | 主推荐合规 Agent 调用接口 |
| `/v1/chat/completions` | OpenAI Chat Completions 兼容接口 |
| `/v1/runs` | 长任务异步接口 |
| `/v1/health`, `/v1/models` | 运维检查 |
| `/upload` | Web UI BFF 文件上传接口，返回服务端可访问文件路径 |
| `/api/hermes/jobs*` | BFF 代理到 Gateway 的 cron job 管理接口 |

## 2. 合规 Agent 能力与调用边界

### 2.1 适用场景

合规 Agent 适合处理以下审查任务：

| 材料类型 | 典型输入 |
| --- | --- |
| 营销物料 | 宣传文案、推广话术、活动页面文案 |
| 海报 | 海报 OCR 文本、海报文案说明 |
| 合同 | 合同条款、协议片段、补充协议 |
| 条款书 | 产品条款、责任说明、免责说明 |
| 产品说明书 | 产品介绍、收益/风险描述、适用人群说明 |
| 其它文本材料 | 需要从合规角度审查的文本内容 |

### 2.2 推荐输入信息

调用方应尽量在 `input` 中提供以下信息：

| 信息 | 是否建议 | 说明 |
| --- | --- | --- |
| `材料类型` | 强烈建议 | 如：营销物料、海报、合同、条款书、产品说明书 |
| `业务场景` | 强烈建议 | 如：保险销售、理财推广、用户协议、活动宣传 |
| `待审内容` | 必填 | 需要审查的原文或可访问文件路径 |
| `审查目标` | 建议 | 如：识别风险、给出依据、输出修改建议 |
| `输出格式` | 建议 | 多 Agent 联动时建议固定格式 |

### 2.3 输出内容预期

合规 Agent 通常会输出：

- 总体结论
- 风险等级或风险状态
- 具体风险点
- 风险原因
- 依据或判断口径
- 修改建议
- 必要时给出替代表述

### 2.4 能力边界

- 本接口不是法律意见书生成接口，输出用于业务合规辅助审查。
- `/v1/responses` 和 `/v1/runs` 不直接接收 `multipart/form-data` 文件上传；文件审查建议先调用 `/upload` 上传文件，再把返回的服务端路径放入 `file_paths`。
- 不建议让上游 Agent 解析 Hermes 内部工具调用字段；多 Agent 联动只依赖最终 message 文本和少量元数据。

## 3. 快速开始：一条 curl 完成合规检测

### 3.1 单次合规检测

测试目的：验证主推荐接口 `/v1/responses` 可以触发合规 Agent，并返回可读审查结果。

```bash
curl "http://js1.blockelite.cn:49505/v1/responses" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-quickstart-001" \
  -d '{
    "model": "hermes-compliance-agent",
    "input": "材料类型：营销物料\n业务场景：理财产品推广\n待审内容：本产品收益稳定，年化收益可达12%，零风险保本，名额有限，立即购买。\n审查目标：请识别合规风险，说明原因，并给出修改建议。",
    "instructions": "请使用中文输出，按【总体结论】【风险点】【修改建议】组织答案。",
    "store": true
  }'
```

### 3.2 提取最终审查文本

测试目的：验证调用方可以只解析最终 message 文本，不依赖 Hermes 内部工具调用。

```bash
curl -s "http://js1.blockelite.cn:49505/v1/responses" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-quickstart-002" \
  -d '{
    "model": "hermes-compliance-agent",
    "input": "材料类型：海报\n业务场景：保险产品宣传\n待审内容：安全无忧，保证收益，适合所有家庭。\n审查目标：请输出风险结论和替代表述。",
    "store": true
  }' | jq -r '.output[] | select(.type=="message") | .content[] | select(.type=="output_text") | .text'
```

### 3.3 上传文件后发起合规检测

测试目的：验证调用方可以先上传本地文件，拿到服务端可访问路径，再通过 `/v1/responses` 的 `file_paths` 触发文件审查。

第一步：上传文件。`file` 是 multipart 表单字段名；同一个请求可以传多个 `file` 字段。

```bash
FILE_PATH=$(curl -s -X POST "http://js1.blockelite.cn:49505/upload" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -F "file=@./91752.pdf" | jq -r '.files[0].path')

echo "$FILE_PATH"
```

第二步：把上传返回的 `path` 放入 `file_paths`。

```bash
curl "http://js1.blockelite.cn:49505/v1/responses" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-file-001" \
  -d "{
    \"model\": \"hermes-compliance-agent\",
    \"input\": \"材料类型：合同\n业务场景：合同文件审查\n审查目标：请审查上传文件中的合规风险，输出风险点、依据和修改建议。\",
    \"file_paths\": [\"${FILE_PATH}\"],
    \"store\": true
  }"
```

## 4. 主接口：`POST /v1/responses`

### 4.1 接口定位

`POST /v1/responses` 是合规 Agent 的主调用接口。适合：

- 单次合规审查
- 多轮审查
- 多 Agent 编排
- 上游系统自动化调用
- 需要保存 response 并后续接续的场景

### 4.2 请求地址

```http
POST http://js1.blockelite.cn:49505/v1/responses
```

### 4.3 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 否 | 兼容字段，建议固定传 `hermes-compliance-agent` |
| `input` | string 或 array | 是 | 本轮审查输入，推荐使用标准审查模板 |
| `file_paths` | array | 否 | 服务端可访问文件路径数组。通常来自 `/upload` 返回的 `files[].path` |
| `instructions` | string | 否 | 本次调用的临时输出要求，会叠加在合规人格之上 |
| `conversation` | string | 否 | 命名会话。相同值会自动接续上一轮 response |
| `previous_response_id` | string | 否 | 精确接续某个 response。不能与 `conversation` 同时使用 |
| `conversation_history` | array | 否 | 调用方显式传入历史。每条必须含 `role` 和 `content` |
| `store` | boolean | 否 | 是否存储 response，默认 `true` |
| `stream` | boolean | 否 | 是否 SSE 流式返回，默认 `false` |
| `truncation` | string | 否 | 可传 `auto`，历史过长时保留最近 100 条 |

### 4.4 文件上传接口：`POST /upload`

`/upload` 是 Web UI BFF 暴露的文件上传接口，用于把调用方本地文件保存到服务端可访问目录。上传成功后，把返回的 `files[].path` 传给 `/v1/responses` 或 `/v1/runs` 的 `file_paths`。

请求要求：

| 项 | 说明 |
| --- | --- |
| Method | `POST` |
| Path | `/upload` |
| Content-Type | `multipart/form-data` |
| 表单字段 | `file`，可重复传多个文件 |
| 单次大小限制 | 50MB |
| Profile | 如需指定 profile，可传 `X-Hermes-Profile` header 或 `?profile=<name>` |

成功响应：

```json
{
  "files": [
    {
      "name": "91752.pdf",
      "path": "/path/to/.hermes-home/profiles/compliance/webui/uploads/8f4a1c2e9b7d6a5f.pdf"
    }
  ]
}
```

常见错误：

| 状态码 | 原因 |
| --- | --- |
| `400` | 未使用 `multipart/form-data`，或缺少 boundary |
| `413` | 上传内容超过 50MB |

### 4.5 文件审查字段：`file_paths`

`file_paths` 必须是字符串数组，每个路径都必须是服务端本机可访问的真实文件路径。推荐只传 `/upload` 返回的 `files[].path`，不要传浏览器本地路径、对象存储私有 URL 或调用方机器上的路径。

文件审查仍然需要传 `input`。`input` 用来说明材料类型、业务场景、审查目标和输出要求；文件正文由合规工具根据 `file_paths` 读取和上传到外部审查流程。

示例：

```json
{
  "model": "hermes-compliance-agent",
  "input": "材料类型：条款书\n业务场景：产品条款审查\n审查目标：请审查文件中的合规风险，输出风险原因、依据和修改建议。",
  "file_paths": [
    "/path/to/.hermes-home/profiles/compliance/webui/uploads/8f4a1c2e9b7d6a5f.pdf"
  ],
  "store": true
}
```

### 4.6 标准合规审查请求模板

推荐把 `input` 组织成稳定文本模板：

```text
材料类型：<营销物料|海报|合同|条款书|产品说明书|其它>
业务场景：<说明材料使用场景>
待审内容：
<原文；如审查文件，可写文件说明，实际路径放入 file_paths>
审查目标：
<识别风险/说明原因/给出依据/输出修改建议/给出替代表述>
输出要求：
<调用方希望的格式>
```

推荐 `instructions`：

```text
你是合规审查 Agent。请只输出审查结论、风险点、依据和修改建议，不要输出与审查无关的闲聊内容。
```

### 4.7 标准响应解析契约

多 Agent 调用方只应依赖以下字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 本次 response id，可用于后续 `previous_response_id` |
| `status` | 响应状态，通常为 `completed` |
| `output[].type == "message"` | 最终自然语言审查结果 |
| `usage` | token 用量统计 |

最终文本提取规则：

```bash
jq -r '.output[] | select(.type=="message") | .content[] | select(.type=="output_text") | .text'
```

不要把以下字段作为业务契约：

| 字段 | 原因 |
| --- | --- |
| `output[].type == "function_call"` | Hermes 内部工具调用，可能变化 |
| `output[].type == "function_call_output"` | Hermes 内部工具结果，可能变化 |
| 工具名称、工具参数、工具返回结构 | 仅用于调试，不适合多 Agent 稳定对接 |

### 4.8 成功响应示例

```json
{
  "id": "resp_abc123",
  "object": "response",
  "status": "completed",
  "model": "hermes-compliance-agent",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "【总体结论】存在高风险表述...\n【风险点】...\n【修改建议】..."
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 100,
    "output_tokens": 200,
    "total_tokens": 300
  }
}
```

### 4.9 单次审查 curl

测试目的：验证标准合规审查模板可以被 Agent 正确理解。

```bash
curl "http://js1.blockelite.cn:49505/v1/responses" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-responses-001" \
  -d '{
    "model": "hermes-compliance-agent",
    "input": "材料类型：营销物料\n业务场景：理财产品推广\n待审内容：本产品收益稳定，年化收益可达12%，零风险保本，名额有限，立即购买。\n审查目标：识别风险等级、风险原因、依据和修改建议。\n输出要求：按【总体结论】【风险点】【修改建议】输出。",
    "instructions": "你是合规审查 Agent。请只输出审查结论、风险点、依据和修改建议。",
    "store": true
  }'
```

### 4.10 命名会话连续审查 curl

测试目的：验证同一个 `conversation` 可以自动接续上下文，适合多轮审查。

测试目的：第一轮建立命名会话并输出首轮风险识别结果。

```bash
curl "http://js1.blockelite.cn:49505/v1/responses" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-conversation-001" \
  -d '{
    "model": "hermes-compliance-agent",
    "conversation": "compliance-demo-20260429",
    "input": "材料类型：海报\n业务场景：保险产品宣传\n待审内容：最高可享8%收益，安全无忧，适合所有家庭。\n审查目标：请先识别主要合规风险。",
    "store": true
  }'
```

测试目的：第二轮复用同一个命名会话，验证 Agent 能基于上一轮结果继续审查。

```bash
curl "http://js1.blockelite.cn:49505/v1/responses" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-conversation-002" \
  -d '{
    "model": "hermes-compliance-agent",
    "conversation": "compliance-demo-20260429",
    "input": "请基于上一轮识别出的风险，给出一版更稳妥的替代表述。",
    "store": true
  }'
```

### 4.11 使用 `previous_response_id` 精确接续 curl

测试目的：验证调用方可以精确串联某次 response，适合多 Agent 工作流中的节点追踪。

测试目的：先获取一个 response id，作为后续节点的精确上游引用。

```bash
RESP_ID=$(curl -s "http://js1.blockelite.cn:49505/v1/responses" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-prev-001" \
  -d '{
    "model": "hermes-compliance-agent",
    "input": "材料类型：合同\n业务场景：服务协议\n待审内容：甲方可单方随时调整服务价格且无需通知乙方。\n审查目标：请识别条款风险并给出修改建议。",
    "store": true
  }' | jq -r '.id')

echo "$RESP_ID"
```

测试目的：使用 `previous_response_id` 接续指定 response，验证链式审查能力。

```bash
curl "http://js1.blockelite.cn:49505/v1/responses" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-prev-002" \
  -d "{
    \"model\": \"hermes-compliance-agent\",
    \"previous_response_id\": \"${RESP_ID}\",
    \"input\": \"请把上一轮的修改建议改写成正式合同条款。\",
    \"store\": true
  }"
```

### 4.12 流式输出 curl

测试目的：验证 SSE 流式输出可用，适合前端实时展示审查过程。

```bash
curl -N "http://js1.blockelite.cn:49505/v1/responses" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes-compliance-agent",
    "input": "材料类型：海报\n业务场景：营销推广\n待审内容：限时抢购，保证升值，错过再等一年。\n审查目标：请流式输出风险识别和修改建议。",
    "stream": true,
    "store": true
  }'
```

`stream=true` 时返回的是 SSE 事件流，不是普通 JSON。客户端应按 SSE 的 `event:` / `data:` 解析。

关键事件：

| 事件 | 说明 |
| --- | --- |
| `response.created` | response 已创建，状态为 `in_progress` |
| `response.output_text.delta` | 文本增量，字段为 `data.delta` |
| `response.output_text.done` | 文本输出结束，字段为 `data.text` |
| `response.completed` | 最终完成事件，完整响应在 `data.response` |
| `response.failed` | 执行失败，错误在 `data.response.error` |

最终结果以 `response.completed` 事件里的 `response.output` 为准。解析规则和非流式一致，只是需要先取出事件 `data.response`：

```text
response.completed.data.response.output[]
  -> select(type == "message")
  -> content[]
  -> select(type == "output_text")
  -> text
```

## 5. 多 Agent 联动规范

### 5.1 推荐调用方式

其他 Agent 调用本合规 Agent 时，固定使用：

```http
POST /v1/responses
```

推荐请求体：

```json
{
  "model": "hermes-compliance-agent",
  "conversation": "upstream-agent-audit-20260429",
  "input": "材料类型：营销物料\n业务场景：上游 Agent 生成的宣传文案复核\n待审内容：...\n审查目标：请输出风险结论、风险点、依据和修改建议。",
  "instructions": "你是被上游多 Agent 编排调用的合规审查节点。请只输出审查结论、风险依据和修改建议，不要输出过程性说明。",
  "store": true
}
```

### 5.2 上游 Agent 解析规则

上游 Agent 只解析：

| 字段 | 用途 |
| --- | --- |
| `id` | 保存为后续 `previous_response_id` |
| `status` | 判断是否完成 |
| 最终 message 文本 | 作为合规审查结论 |
| `usage` | 记录成本或监控用量 |

最终 message 文本提取：

```bash
jq -r '.output[] | select(.type=="message") | .content[] | select(.type=="output_text") | .text'
```

### 5.3 会话策略

| 策略 | 推荐场景 | 说明 |
| --- | --- | --- |
| `conversation` | 业务级连续审查 | 同一个业务单据或同一个上游任务使用同一个 conversation |
| `previous_response_id` | 精确链路串联 | 明确要接续某一次 response 时使用 |
| `conversation_history` | 调用方显式传历史 | 适合上游系统自己管理上下文；如果不希望服务端保存会话，不要同时传 `conversation` / `previous_response_id`，并设置 `store: false` |

推荐默认：

```text
多 Agent 编排使用 conversation。
需要审计精确链路时，同时保存每次返回的 response.id。
```

### 5.4 幂等与重试

非流式 POST 请求建议传 `Idempotency-Key`。

推荐格式：

```text
<caller>-<business_id>-<attempt_or_timestamp>
```

示例：

```text
risk-agent-policy-20260429-001
```

注意：

- 同一个 `Idempotency-Key` 搭配完全相同请求体，会复用缓存结果。
- 幂等缓存是服务端内存缓存，有过期时间；不要把它当作长期审计记录。
- 同一个 `Idempotency-Key` 不应搭配不同请求体复用；当前实现不会把不同请求体视为冲突错误，而是重新执行并更新缓存。
- 流式请求不建议使用幂等缓存。

## 6. 兼容接口：`POST /v1/chat/completions`

### 6.1 接口定位

该接口用于兼容 OpenAI Chat Completions 客户端，如 Open WebUI、LobeChat、LibreChat。新系统或多 Agent 编排不建议优先使用该接口。

### 6.2 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 否 | 兼容字段 |
| `messages` | array | 是 | OpenAI chat message 列表 |
| `stream` | boolean | 否 | 是否流式 |

注意：

- `system` 会作为本次临时补充指令。
- 最后一条 `user` 是本轮输入。
- 之前的 `user` / `assistant` 会作为历史。
- 生成参数如 `temperature`、`max_tokens`、`top_p` 不作为稳定契约，Agent 行为由 Hermes profile 决定。

### 6.3 非流式 curl

测试目的：验证 OpenAI Chat Completions 兼容接口可触发合规 Agent。

```bash
curl "http://js1.blockelite.cn:49505/v1/chat/completions" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-chat-001" \
  -d '{
    "model": "hermes-compliance-agent",
    "messages": [
      {
        "role": "system",
        "content": "请使用中文输出，格式为：结论、风险点、修改建议。"
      },
      {
        "role": "user",
        "content": "请检测这段宣传语：本理财产品安全可靠，承诺保本，收益领先同类。"
      }
    ],
    "stream": false
  }'
```

测试目的：验证 Chat Completions 兼容响应可以按 `.choices[0].message.content` 提取最终文本。

```bash
curl -s "http://js1.blockelite.cn:49505/v1/chat/completions" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-chat-002" \
  -d '{
    "model": "hermes-compliance-agent",
    "messages": [
      {"role": "user", "content": "请检测文案：收益无上限，闭眼买。"}
    ]
  }' | jq -r '.choices[0].message.content'
```

### 6.4 流式 curl

测试目的：验证 Chat Completions SSE 流式输出可用。

```bash
curl -N "http://js1.blockelite.cn:49505/v1/chat/completions" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes-compliance-agent",
    "messages": [
      {"role": "user", "content": "请流式输出这段合同条款的合规风险：平台可无需理由冻结用户账户。"}
    ],
    "stream": true
  }'
```

## 7. 长任务接口：`POST /v1/runs`

### 7.1 接口定位

`/v1/runs` 用于长时间合规分析。创建后立即返回 `run_id`，调用方再通过 SSE 订阅事件。

注意：

- 该接口不是多 Agent 联动的默认接口。
- 该接口不使用 `conversation`，会话连续性使用 `session_id`。
- 该接口也支持 `file_paths`，用法与 `/v1/responses` 相同：先通过 `/upload` 拿到 `files[].path`，再传入 `file_paths`。
- 如果只是普通合规审查，优先使用 `/v1/responses`。

常用请求字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `input` | string 或 array | 是 | 本轮审查输入 |
| `file_paths` | array | 否 | 服务端可访问文件路径数组，通常来自 `/upload` |
| `instructions` | string | 否 | 本次调用的临时输出要求 |
| `session_id` | string | 否 | 异步任务的会话 ID；相同值可复用会话上下文 |
| `conversation_history` | array | 否 | 调用方显式传入历史 |
| `previous_response_id` | string | 否 | 接续已存储 response 的历史和 session |

### 7.2 创建 run curl

测试目的：创建异步合规审查任务，立即拿到 `run_id`。

```bash
RUN_ID=$(curl -s "http://js1.blockelite.cn:49505/v1/runs" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-runs-001" \
  -d '{
    "input": "材料类型：产品说明书\n业务场景：理财产品说明\n待审内容：产品灵活、安全、收益可观，适合全部投资者，历史业绩代表未来表现。\n审查目标：请完整审查并输出风险清单和逐条修改建议。",
    "instructions": "按高/中/低风险分组输出。",
    "session_id": "async-compliance-demo-20260429"
  }' | jq -r '.run_id')

echo "$RUN_ID"
```

### 7.3 订阅 run 事件 curl

测试目的：订阅指定 run 的 SSE 事件，实时获取文本增量、工具进度和最终结果。

```bash
curl -N "http://js1.blockelite.cn:49505/v1/runs/${RUN_ID}/events" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001"
```

事件示例：

```json
{"event":"message.delta","run_id":"run_xxx","delta":"总体结论"}
{"event":"tool.started","run_id":"run_xxx","tool":"compliance_review","preview":"..."}
{"event":"tool.completed","run_id":"run_xxx","tool":"compliance_review","duration":1.234,"error":false}
{"event":"run.completed","run_id":"run_xxx","output":"最终审查结果...","usage":{"input_tokens":100,"output_tokens":200,"total_tokens":300}}
```

## 8. 运维与附录

### 8.1 健康检查

BFF 健康检查：

测试目的：验证测试环境入口可访问。

```bash
curl "http://js1.blockelite.cn:49505/health" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001"
```

Gateway 健康检查：

测试目的：验证 BFF 可以代理访问 Gateway。

```bash
curl "http://js1.blockelite.cn:49505/v1/health" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001"
```

模型列表：

测试目的：验证 OpenAI 兼容客户端可以获取模型列表。

```bash
curl "http://js1.blockelite.cn:49505/v1/models" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001"
```

### 8.2 Cron Job 管理

Cron job 用于定时合规检测。任务触发时会进入 Hermes Agent 外壳并使用合规人格。通过 BFF 调用时，路径使用 `/api/hermes/jobs*`。

查询任务列表：

测试目的：验证可查询当前定时合规任务。

```bash
curl "http://js1.blockelite.cn:49505/api/hermes/jobs?include_disabled=true" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001"
```

创建测试任务并保存 `JOB_ID`：

测试目的：验证任务创建能力，并为后续查询、更新、触发、删除接口准备 job id。

```bash
JOB_ID=$(curl -s "http://js1.blockelite.cn:49505/api/hermes/jobs" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-20260429-001-cron-create-001" \
  -d '{
    "name": "合规接口文档测试任务",
    "schedule": "0 9 * * *",
    "prompt": "请做一次合规巡检测试，输出一句测试完成。",
    "deliver": "local"
  }' | jq -r '.job.id // .job.job_id // .job_id')

echo "$JOB_ID"
```

查询单个任务：

测试目的：验证可以读取指定定时任务详情。

```bash
curl "http://js1.blockelite.cn:49505/api/hermes/jobs/${JOB_ID}" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001"
```

更新任务：

测试目的：验证可以更新指定定时任务的名称、提示词和启用状态。

```bash
curl -X PATCH "http://js1.blockelite.cn:49505/api/hermes/jobs/${JOB_ID}" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "合规接口文档测试任务-已更新",
    "prompt": "请做一次合规巡检测试，输出测试完成和当前风险摘要。",
    "enabled": true
  }'
```

立即触发任务：

测试目的：验证可以手动触发一次定时任务，便于联调任务执行链路。

```bash
curl -X POST "http://js1.blockelite.cn:49505/api/hermes/jobs/${JOB_ID}/run" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001" \
  -H "Idempotency-Key: test-20260429-001-cron-run-001"
```

删除测试任务：

测试目的：清理本节创建的测试任务，避免测试环境残留。

```bash
curl -X DELETE "http://js1.blockelite.cn:49505/api/hermes/jobs/${JOB_ID}" \
  -H "Authorization: Bearer f200ae37ed8103b16566ff9f62d30b3c18aa4a4e5791a299ce1deb78e0a306a0" \
  -H "X-Request-Id: test-20260429-001"
```

### 8.3 错误格式

OpenAI 兼容接口错误通常为：

```json
{
  "error": {
    "message": "Missing 'input' field",
    "type": "invalid_request_error",
    "code": null
  }
}
```

Cron job 接口错误通常为：

```json
{
  "error": "Job not found"
}
```

常见 HTTP 状态码：

| 状态码 | 含义 | 常见原因 |
| --- | --- | --- |
| `200` | 成功 | 请求完成 |
| `202` | 已接受 | 异步 run 已创建 |
| `400` | 请求参数错误 | JSON 格式错误、缺少 `input`、job 字段非法 |
| `401` | 未认证 | token 缺失或错误 |
| `404` | 不存在 | response、job 或 run 不存在 |
| `429` | 限流 | 并发 run 过多 |
| `500` | 服务端错误 | Agent 执行异常或上游模型异常 |

## 9. 测试验收清单

按以下顺序测试：

1. `GET /health` 验证 BFF 可访问。
2. `GET /v1/health` 验证 Gateway 可通过 BFF 代理访问。
3. `POST /v1/responses` 跑一次单轮合规检测。
4. 如需文件审查，先 `POST /upload` 上传文件，再把返回路径传给 `file_paths`。
5. `POST /v1/responses` 使用 `conversation` 跑两轮连续审查。
6. 用 `jq` 提取最终 message 文本。
7. 如需流式输出，测试 `stream=true` 并解析 `response.completed` 事件。
8. 如需长任务，测试 `/v1/runs` 和 `/v1/runs/{run_id}/events`。
9. 如需定时任务，测试 `/api/hermes/jobs*`，创建后记得删除测试任务。

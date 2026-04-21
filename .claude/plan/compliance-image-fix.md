---
name: fix-compliance-image-classification
description: Fix image classification by routing to external workflow API instead of relying on local OCR + DeepSeek text model
type: project
---

# Fix: 图片分类走外部工作流 API

## 问题

图片文件在合规检测中分类失败，原因链路：
1. 本地 OCR（tesseract）可能未安装或提取文本为空
2. 分类模型 deepseek-chat 不支持 `image_url` vision 输入
3. 图片 preview asset 被忽略，分类器只拿到空文本 → 分类失败 → 整个 review 报错

但外部工作流（Dify）本身**支持上传图片做检测**，只是分类阶段没有利用这个能力。

## 方案

图片优先走外部工作流分类，失败再 fallback 到本地 LLM。

### 改动文件（4 个）

#### 1. `auto_classification_service.py`

- 移除 `del force_model`，同时删除 `force_model` 参数
- 新增 `workflow_credentials` 参数（`WorkflowCredentialSet | None`）
- 新增 `_classify_image_via_external_workflow()` 方法：
  - 检查 `workflow_client` 和 `general_api_key` 是否可用
  - 上传图片到外部 API → 得到 `upload_file_id`
  - 调用 `run_material_classification_workflow(input_type="image")` → 得到 answer
  - 解析 answer JSON → 返回 `AutoClassification(source="external_workflow")`
  - 任何步骤失败 → 返回 `None`，fallback 到本地 LLM
- 修改 `classify()` 方法：在 cache lookup 之后、`_build_source_bundle` 之前，检测图片 → 先尝试外部工作流

#### 2. `external_workflow_client.py`

- `build_material_classification_payload()` 新增 `input_type: str = "document"` 参数
- `run_material_classification_workflow()` 新增 `input_type: str = "document"` 参数，转发给 payload builder

#### 3. `runtime.py`

- `MaterialClassificationService` 构造时传入 `client=workflow_client` 和 `workflow_credentials=settings.workflow_credentials`

#### 4. `ingest_service.py`（清理之前讨论的 bug）

- `_classify_source` 移除 `context_text` 和 `force_model` 参数传递
- `_build_request` 新增 `context_text` 参数，将用户文字注入 `ComplianceRequest.query`

### 不改的文件

- `ingest_service.py` 的 `_classify_source` 调用接口不变（只是去掉死参数）
- `result_adapter.py` / `progress_bridge.py`（上一轮已改完，全部输出给 LLM）
- `material_skill_service.py`（下游工作流执行不受影响）

## 图片分类流程（改后）

```
classify(local_path="xxx.png")
  → cache lookup
  → detect is_image = True
  → _classify_image_via_external_workflow()
    → upload_file(local_path) → upload_file_id
    → run_material_classification_workflow(upload_file_id, input_type="image")
    → parse JSON answer → AutoClassification
    → return（成功）
  → 如果外部失败：fallback 到本地 LLM（OCR + deepseek-chat，降级但可用）
```

非图片文件流程不变。
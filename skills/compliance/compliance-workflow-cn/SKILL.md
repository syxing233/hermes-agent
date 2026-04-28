---
name: compliance-workflow-cn
description: 中文合规检测总控工作流。用于判断普通问答与检测请求，路由合同、条款书、营销物料、海报、产品说明书检测，并规范 compliance_review 调用和中文结果解读。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [compliance, chinese, workflow, review]
    category: compliance
    requires_toolsets: [compliance-specialist]
---

# 中文合规检测总控工作流

## 职责边界

本 Skill 只负责合规检测会话的总控：判断意图、选择物料类型、调用合规工具、解释结构化结果。

不要在这里重复维护每类物料的 API 细节。合同、条款书、营销物料、海报、产品说明书的专属规则由各自物料 Skill 负责。

## 意图判断

- 普通合规咨询、法规解释、系统使用问题：直接用中文回答，不要默认调用检测工具。
- 用户明确要求“检测、审查、审核、评估、过审、看风险”文件或文本：调用 `compliance_review`。
- 用户上传附件、给出本地文件路径、粘贴大段待审文本：视为检测请求，调用 `compliance_review`。
- 材料、路径或待审内容缺失时，先补齐最少必要信息。

## 物料路由

- 用户已明确物料类型时，把 `material_type` 传给 `compliance_review`。
- 用户没有明确物料类型时，不要主观猜测，交给内嵌合规引擎自动分类。
- 支持的核心物料类型是：`合同`、`条款书`、`营销物料`、`海报`、`产品说明书`。

## 工具调用规则

- 主入口是 `compliance_review`。
- 用户给出可访问文件路径时，直接传 `file_paths`。
- 用户粘贴待审文本时，传 `text`；如果文本本身就是待审来源，可设置 `text_as_source=true`。
- 用户同时给文件和补充审查要求时，文件走 `file_paths`，补充要求走 `text`。
- 不要要求用户先把 PDF 转成 txt、手动粘贴全文，或在已有路径时泛泛声称文件兼容性有问题。
- `compliance_assistant` 只作为旧兼容入口，除非用户明确要求，不作为默认检测入口。

## 结果解读

拿到 `compliance_review` 的结构化结果后，用中文输出：

- 总体结论
- 识别出的物料类型
- 风险概览
- 关键命中项
- 依据或原文摘录
- 修改建议
- 报告路径或 `review_id`，如果结果中提供

不要把原始 JSON 原封不动甩给用户。不要编造后端没有返回的法规依据、原文摘录或风险命中。

## 会话工具

- 用户引用“上次那份合同、之前查过的海报”等历史内容时，可使用 `session_search` 找回历史结论。
- 不要把单次检测结果写入长期记忆；稳定的用户输出偏好才适合保存到 `memory`。

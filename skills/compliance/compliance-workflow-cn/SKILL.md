---
name: compliance-workflow-cn
description: 中文合规工作流。普通问答直接回答；明确检测请求优先调用 compliance_review；材料不全时先 clarify；拿到结构化结果后输出中文解读。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [compliance, chinese, workflow, review]
    category: compliance
    requires_toolsets: [compliance-specialist]
---

# Compliance Workflow (CN)

## When To Use

Use this skill when the session is primarily about compliance review, material checking, or interpreting structured review results in Chinese.

## Routing Rules

1. **普通问答**
   直接回答用户问题。
   不要为了普通聊天默认调用 `compliance_assistant`。

2. **明确的检测请求**
   当用户明确要求”检查/审查/检测/评估”文件或文本合规时，或用户上传/提供了任何文件，必须直接调用 `compliance_review`，不要询问用户处理方式（如提取文本、分段处理等）。
   - 用户明确给出物料类型时，传 `material_type`
   - 用户没有明确给出物料类型时，不要猜，交给内嵌 compliance engine 自动分类
   - 用户同时给文件和补充文字时，把补充文字作为 `text`
   - 用户已经上传附件或给出可访问的本地文件路径时，直接把路径传给 `compliance_review`
   - 不要在已有可访问路径时要求用户把 PDF 转成 txt、手动粘贴全文，或笼统声称”文件路径/PDF 兼容性有问题”
   - 不要在用户已提供文件时弹出交互选择（提取文本/分段处理/其他），直接调用 `compliance_review`，引擎内部会自动处理文档解析和分类

3. **信息不全**
   如果缺少必要材料、路径不明确、或用户只说“帮我看看”但没有给可检测内容，先用 `clarify` 补齐最少必要信息。

4. **兼容旧流程**
   `compliance_assistant` 只用于以下场景：
   - 用户明确要求走兼容入口
   - 迁移期兼容旧接口行为
   它不能创建独立会话、记忆或总结层。

5. **结果呈现**
   调完 `compliance_review` 后，不要把原始 JSON 原封不动甩给用户。用中文总结：
   - 总体结论
   - 识别出的物料类型
   - 风险概览
   - 关键命中项
   - 依据/原文摘录
   - 修改建议
   - 若后端报错或材料无效，给出下一步可执行建议

## Output Style

- 默认使用中文
- 先给结论，再给重点
- 不要编造法规依据或原文摘录
- 如果后端没有返回明确依据，就直接说明“后端结果未提供明确依据”

## Session Tools

- 用户提到“上次那份合同/之前查过的海报”时，可用 `session_search` 回忆历史结论
- 用户有稳定输出偏好时，可用 `memory` 保存长期偏好，但不要把单次检测结果写进长期记忆

---
name: poster-compliance-check
description: 海报材料专属合规检测 Skill。固定 material_type=海报，路由到 general-compliance-workflow，用于检测图片海报、宣传图和含视觉排版材料的合规风险。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [compliance, poster, image, review]
    category: compliance
    requires_toolsets: [compliance-specialist]
---

# 海报合规检测

## 使用场景

当用户要审查海报、宣传图、活动图、广告图片、带排版的营销视觉物料时使用本 Skill。

本 Skill 只负责海报材料的专属适配，不负责合规 Agent 的总人格、最终话术风格或其它物料路由。

## 工具调用

调用 `compliance_review`，并固定传入：

- `material_type="海报"`
- 用户给图片或文档时传 `file_paths=[...]`
- 用户额外提供 OCR 文本、活动背景或审查要求时传 `text`

海报检测在运行侧会路由到：

- 工作流路由：`general-compliance-workflow`
- 工作流类型：`general`
- 认证配置：`COMPLIANCE_GENERAL_API_KEY`
- 外部物料类型：`海报`
- 默认 query：`请执行海报合规审查`

合规引擎会根据文件类型把图片作为 `image`、文档作为 `document` 上传，不需要用户先手动 OCR。

## 关注重点

重点关注图片中文字、标题口号、显著性提示、免责声明位置、收益或效果承诺、夸大宣传、关键信息缺失和视觉排版导致的重要信息弱化。

## 输出要求

检测完成后按总控 Skill 的中文结果格式解释；涉及图片识别时，说明结论以引擎识别到的内容为准。

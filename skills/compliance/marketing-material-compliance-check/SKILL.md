---
name: marketing-material-compliance-check
description: 营销物料专属合规检测 Skill。固定 material_type=营销物料，路由到 general-compliance-workflow，用于检测宣传文案、销售话术和营销材料风险。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [compliance, marketing, review]
    category: compliance
    requires_toolsets: [compliance-specialist]
---

# 营销物料合规检测

## 使用场景

当用户要审查宣传文案、销售话术、活动介绍、广告素材正文、营销页面文本等营销物料时使用本 Skill。

本 Skill 只负责营销物料的专属适配，不负责合规 Agent 的总人格、最终话术风格或其它物料路由。

## 工具调用

调用 `compliance_review`，并固定传入：

- `material_type="营销物料"`
- 用户给文件时传 `file_paths=[...]`
- 用户粘贴文案或补充审查要求时传 `text`

营销物料检测在运行侧会路由到：

- 工作流路由：`general-compliance-workflow`
- 工作流类型：`general`
- 认证配置：`COMPLIANCE_GENERAL_API_KEY`
- 外部物料类型：`营销物料`
- 默认 query：`请执行营销物料合规审查`

## 关注重点

重点关注绝对化用语、收益承诺、夸大宣传、误导性表述、竞品比较、资质背书、风险提示缺失、适当性提示缺失和监管禁止性表述。

## 输出要求

检测完成后按总控 Skill 的中文结果格式解释，区分“文案表述风险”和“产品条款风险”。

---
name: clausebook-compliance-check
description: 条款书材料专属合规检测 Skill。固定 material_type=条款书，路由到 general-compliance-workflow，用于输出条款书结构化风险、依据和修改建议。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [compliance, clausebook, review]
    category: compliance
    requires_toolsets: [compliance-specialist]
---

# 条款书合规检测

## 使用场景

当用户要审查保险条款书、产品条款、责任说明、保障范围、免责条款等条款书类材料时使用本 Skill。

本 Skill 只负责条款书材料的专属适配，不负责合规 Agent 的总人格、最终话术风格或其它物料路由。

## 工具调用

调用 `compliance_review`，并固定传入：

- `material_type="条款书"`
- 用户给文件时传 `file_paths=[...]`
- 用户粘贴条款内容或补充审查要求时传 `text`

条款书检测在运行侧会路由到：

- 工作流路由：`general-compliance-workflow`
- 工作流类型：`general`
- 认证配置：`COMPLIANCE_GENERAL_API_KEY`
- 外部物料类型：`条款书`
- 默认 query：`请执行条款书合规审查`

## 关注重点

重点关注保障范围、责任免除、等待期、犹豫期、宽限期、理赔条件、投保人与被保险人条件、费用扣除、重要提示和风险揭示是否完整清晰。

## 输出要求

检测完成后按总控 Skill 的中文结果格式解释，不要把条款书结论泛化成合同审查结论。

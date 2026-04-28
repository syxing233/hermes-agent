---
name: product-handbook-compliance-check
description: 产品说明书专属合规检测 Skill。固定 material_type=产品说明书，路由到 general-compliance-workflow，但使用产品说明书专属 COMPLIANCE_HANDBOOK_API_KEY。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [compliance, product-handbook, review]
    category: compliance
    requires_toolsets: [compliance-specialist]
---

# 产品说明书合规检测

## 使用场景

当用户要审查产品说明书、产品手册、服务说明、权益说明、使用说明等说明书类材料时使用本 Skill。

本 Skill 只负责产品说明书材料的专属适配，不负责合规 Agent 的总人格、最终话术风格或其它物料路由。

## 工具调用

调用 `compliance_review`，并固定传入：

- `material_type="产品说明书"`
- 用户给文件时传 `file_paths=[...]`
- 用户粘贴说明书内容或补充审查要求时传 `text`

产品说明书检测在运行侧会路由到：

- 工作流路由：`general-compliance-workflow`
- 工作流类型：`general`
- 认证配置：`COMPLIANCE_HANDBOOK_API_KEY`
- 外部物料类型：`产品说明书`
- 默认 query：`请执行产品说明书合规审查`

注意：产品说明书虽然使用 general 工作流路由，但认证 key 不是 `COMPLIANCE_GENERAL_API_KEY`。

## 关注重点

重点关注产品范围、适用条件、限制条件、责任边界、费用说明、用户义务、服务承诺、风险提示、前后表述一致性和重要信息完整性。

## 输出要求

检测完成后按总控 Skill 的中文结果格式解释，不要把产品说明书误判为营销物料或条款书。

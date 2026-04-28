---
name: contract-compliance-check
description: 合同材料专属合规检测 Skill。固定 material_type=合同，路由到 contract-review-2.0 工作流，并使用合同专属参数输出结构化风险、依据、摘录和修改建议。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [compliance, contract, review]
    category: compliance
    requires_toolsets: [compliance-specialist]
---

# 合同合规检测

## 使用场景

当用户要审查合同、协议、委托合同、采购合同、服务合同、合作协议等合同类文件或文本时使用本 Skill。

本 Skill 只负责合同材料的专属适配，不负责合规 Agent 的总人格、最终话术风格或其它物料路由。

## 工具调用

调用 `compliance_review`，并固定传入：

- `material_type="合同"`
- 用户给文件时传 `file_paths=[...]`
- 用户粘贴合同文本或补充审查要求时传 `text`

合同检测在运行侧会路由到：

- 工作流路由：`contract-review-2.0`
- 工作流类型：`contract`
- 认证配置：`COMPLIANCE_CONTRACT_API_KEY`
- 默认 query：`请执行合同合规审查`

## 合同专属参数

合同工作流支持以下专属字段，由合规引擎从请求或分类结果中补齐：

- `contract_type`：合同类型，缺省为 `通用`
- `statement`：审查立场，缺省为 `甲方`
- `scale`：谈判强弱势，缺省为 `均势`
- `json_rules`：合同审查规则；用户未提供时使用内置合同规则兜底

如果用户明确指定审查立场、合同类型或强弱势，应把这些要求写入 `text`，让检测引擎结合材料处理。

## 关注重点

重点关注主体资格、合同标的、权利义务、付款与发票、违约责任、解除终止、保密条款、争议解决、法律引用有效性等合同风险。

## 输出要求

检测完成后按总控 Skill 的中文结果格式解释，不要伪造合同条款、法规依据或后端未返回的风险项。

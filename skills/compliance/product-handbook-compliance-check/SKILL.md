---
name: product-handbook-compliance-check
description: 对产品说明书材料调用 Hermes 内嵌合规引擎，固定 material_type=产品说明书，用于输出结构化合规检测结果。
---

# Product Handbook Compliance Check

## When To Use

Use this skill when the material is a 产品说明书 and the user wants structured review findings.

## How To Route

Call `compliance_review` with:

- `material_type="产品说明书"`
- `file_paths=[...]` for files
- `text` for inline content or review instructions

## Expected Output

Expect a compact Hermes-friendly result plus artifact storage:

- `review_id`
- `summary`
- `top_items`
- `status_trace_summary`
- `artifact_path`

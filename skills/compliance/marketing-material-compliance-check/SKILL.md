---
name: marketing-material-compliance-check
description: 对营销物料调用 Hermes 内嵌合规引擎，固定 material_type=营销物料，用于输出结构化合规检测结果。
---

# Marketing Material Compliance Check

## When To Use

Use this skill when the source is 营销物料 and the user wants a structured compliance review.

## How To Route

Call `compliance_review` with:

- `material_type="营销物料"`
- `file_paths=[...]` for files
- `text` for pasted content or审查重点

## Expected Output

The embedded engine returns:

- `review_id`
- `summary`
- `top_items`
- `status_trace_summary`
- `artifact_path`

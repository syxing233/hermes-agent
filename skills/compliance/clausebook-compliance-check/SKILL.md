---
name: clausebook-compliance-check
description: 对条款书材料调用 Hermes 内嵌合规引擎，固定 material_type=条款书，用于输出结构化合规检测结果。
---

# Clausebook Compliance Check

## When To Use

Use this skill when the source material is a 条款书 and the user wants a structured compliance review.

## How To Route

Call `compliance_review` with:

- `material_type="条款书"`
- `file_paths=[...]` for uploaded/local files
- `text` for pasted text or additional审查要求

## Expected Output

Expect Hermes to receive a compact result with a stored artifact:

- `review_id`
- `summary`
- `top_items`
- `status_trace_summary`
- `artifact_path`

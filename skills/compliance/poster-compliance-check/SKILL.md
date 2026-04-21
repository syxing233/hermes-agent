---
name: poster-compliance-check
description: 对海报材料调用 Hermes 内嵌合规引擎，固定 material_type=海报，用于输出结构化合规检测结果。
---

# Poster Compliance Check

## When To Use

Use this skill when the material is a 海报 and the user wants structured review findings.

## How To Route

Call `compliance_review` with:

- `material_type="海报"`
- `file_paths=[...]` for files
- `text` for pasted OCR text or审查说明

## Expected Output

The embedded engine returns a compact result plus artifact storage:

- `review_id`
- `summary`
- `top_items`
- `status_trace_summary`
- `artifact_path`

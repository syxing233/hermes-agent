---
name: contract-compliance-check
description: 对合同材料调用 Hermes 内嵌合规引擎，固定 material_type=合同，用于输出结构化风险、依据、摘录和修改建议。
---

# Contract Compliance Check

## When To Use

Use this skill when the material is a contract and the user wants a structured compliance review in Hermes.

## How To Route

Call `compliance_review` with:

- `material_type="合同"`
- `file_paths=[...]` when the user provides files
- `text` for pasted contract text or supplementary review instructions

## Expected Output

The embedded engine returns a compact payload with:

- `review_id`
- `summary`
- `top_items`
- `status_trace_summary`
- `artifact_path`

Do not ask Hermes to shell out to standalone scripts or an external backend for the main path.

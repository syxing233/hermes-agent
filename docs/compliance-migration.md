# Compliance Migration

## Migrated Into Hermes

These source areas were migrated into the repository under
[compliance_agent](/Users/syxing/Documents/hermes-agent/compliance_agent):

- `models/`
- `graph/`
- `skills/`
- core services:
  `auto_classification_service.py`,
  `document_service.py`,
  `external_workflow_client.py`,
  `ingest_service.py`,
  `material_skill_service.py`,
  `adjudication_service.py`,
  `hitl_service.py`,
  `rules_service.py`,
  `suggestion_service.py`

## Downgraded To Standalone Compatibility

These are no longer on the Hermes main path and now live under
[compliance_agent/standalone](/Users/syxing/Documents/hermes-agent/compliance_agent/standalone):

- `assistant_service.py`
- `conversation_memory_service.py`
- `report_analysis_service.py`
- `api_app.py`
- `main.py`

## Hermes-Specific Adapters

New Hermes integration files live under
[compliance_agent/hermes](/Users/syxing/Documents/hermes-agent/compliance_agent/hermes):

- `runtime.py`
- `config_adapter.py`
- `request_adapter.py`
- `result_adapter.py`
- `artifact_store.py`
- `progress_bridge.py`
- `session_policy.py`

## Skill Alignment

Bundled skill docs now live under
[skills/compliance](/Users/syxing/Documents/hermes-agent/skills/compliance)
and align with `compliance_agent/skills/registry.py` for:

- `contract-compliance-check`
- `clausebook-compliance-check`
- `product-handbook-compliance-check`
- `marketing-material-compliance-check`
- `poster-compliance-check`

They now instruct Hermes to call `compliance_review` directly instead of
shelling out to external scripts.

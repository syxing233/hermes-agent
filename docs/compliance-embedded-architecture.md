# Embedded Compliance Architecture

Hermes is the only agent shell. The embedded `compliance_agent` package is a
domain execution engine, not a second assistant.

## Ownership Split

- Hermes owns personality, primary LLM, clarify, memory, session persistence, user interaction, and final narration.
- `compliance_agent` owns file ingest, document parsing, auto-classification, material routing, external workflow calls, and structured review facts.

## Main Path

1. `tools/compliance_tool.py` adapts Hermes tool args into `IngestSource` inputs.
2. `compliance_agent/hermes/runtime.py` builds cached runtime objects.
3. `IngestReviewService` runs classification + workflow execution.
4. `compliance_agent/hermes/result_adapter.py` emits a compact tool result.
5. `compliance_agent/hermes/artifact_store.py` writes the full report to:
   `get_hermes_home()/compliance/reviews/<review_id>.json`

## Session Policy

- Compact review summaries can enter the current turn context.
- Full structured reports stay in artifacts.
- Single review results do not go into Hermes long-term memory.
- Historical recall should use Hermes `session_search`, not a separate compliance conversation store.

## Optional Dependencies

- `langgraph` stays optional via the `compliance-graph` extra.
- `pypdf` stays optional via the `compliance-pdf` extra.
- The default embedded review path does not require either one.

## Configuration

Hermes reads non-secret compliance settings from `config.yaml`:

```yaml
compliance:
  workflow:
    base_url: http://js2.blockelite.cn:23280/v1
    timeout_seconds: 30
    max_retries: 2

  classification:
    primary:
      provider: deepseek
      model: deepseek-chat
    review:
      provider: deepseek
      model: deepseek-chat
    policy:
      low_confidence_threshold: 0.78
      small_review_threshold: 0.82
      direct_big_min_parse_confidence: 0.45
      direct_big_parsers: [pdf_ocr, image_ocr]
      review_on_hint_conflict: true
      review_on_ambiguous_types: true
      max_text_chars: 6000
      preview_pages: 1
      cache_db_path: .data/material_classification_cache.sqlite3
      prompt_version: material-classification-v2

  parsing:
    min_confidence: 0.45
    min_chars: 80

  hitl:
    confidence_threshold: 0.55
    high_risk_threshold: 1

  artifacts:
    enabled: true
    dir: ""
    markdown: true

  runtime:
    enable_graph: false
```

Project-local `.env` only keeps workflow secrets:

```bash
COMPLIANCE_CONTRACT_API_KEY=...
COMPLIANCE_GENERAL_API_KEY=...
COMPLIANCE_HANDBOOK_API_KEY=...
```

Classification/review provider auth now reuses Hermes provider resolution
(`auth.json`, provider env vars, credential pools, custom providers). Legacy
flat compliance keys and `COMPLIANCE_AGENT_BASE_URL` are no longer part of the
embedded main path.

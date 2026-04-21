# Compliance Agent Integration

Hermes now embeds the compliance engine directly in-process. The old
`COMPLIANCE_AGENT_BASE_URL` HTTP bridge is no longer the main architecture.

See:

- [docs/compliance-embedded-architecture.md](/Users/syxing/Documents/hermes-agent/docs/compliance-embedded-architecture.md)
- [docs/compliance-migration.md](/Users/syxing/Documents/hermes-agent/docs/compliance-migration.md)

## Runtime Summary

- Hermes is the only assistant/session/memory shell.
- `compliance_review` calls the embedded `compliance_agent` package directly.
- Full reports are written to `get_hermes_home()/compliance/reviews/<review_id>.json`.
- Compliance skill docs are bundled under [skills/compliance](/Users/syxing/Documents/hermes-agent/skills/compliance).

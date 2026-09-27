# OpsPilot contributor contract

OpsPilot is a production control plane. Deterministic refusal and explicit evidence are product features.

- Keep Core product-agnostic. Product names, hostnames, service units, provider secrets and business-specific checks belong in adapters.
- Never weaken a production gate through configuration. Environment classification is Core-owned.
- Production mutations require release-bound explicit confirmation and regression tests.
- Evaluate candidate/production policy before starting adapter processes.
- Persist bounded evidence; avoid storing raw subprocess output that may contain credentials.
- Add tests for every new state transition, failure path, rollback path or confirmation rule.
- Preserve backward compatibility during consumer migrations. Prefer shadow/dual-run validation before transferring authority.
- Do not make live production mutation part of unit tests.
- Runtime verification outside loopback must use HTTPS.
- New provider-specific traffic switching belongs in a project adapter or provider plugin, never generic Core.

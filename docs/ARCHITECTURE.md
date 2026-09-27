# OpsPilot architecture

OpsPilot is intentionally separate from the software it deploys.

```text
                   OpsPilot Core
                        |
              policy / state / evidence
                        |
                 Adapter contract
                        |
        +---------------+---------------+
        |               |               |
    DevControl       WorkDone        Other app
     adapter          adapter          adapter
```

## Core

`opspilot/core.py` defines lifecycle states, ordering, failure semantics and production confirmations.

Core must not encode product hostnames, service units, OAuth providers, cloud vendors or business-specific tests.

## Project contract

`opspilot/config.py` validates project-owned runtime and adapter declarations. Core owns each action's environment classification so configuration cannot relabel a production operation as staging.

## Runtime verification

`opspilot/runtime.py` verifies live runtime identity through project-declared JSON Pointers. Products can expose different health schemas while OpsPilot still binds release revision, schema digest and named readiness checks.

Non-loopback runtime verification requires HTTPS.

## Release identity

`opspilot/release.py` verifies Ed25519-signed immutable release manifests and binds them to expected component, release and revision identity.

## Adapter executor

`opspilot/executor.py` launches explicit argv arrays after policy gates have passed. Bounded evidence stores return code, byte counts and SHA-256 hashes rather than raw stdout/stderr.

## Candidate gate

Candidate promotion can require:

- a verified runtime environment;
- exact release revision parity;
- named runtime checks;
- an Ed25519-verified release manifest;
- component identity;
- schema-digest parity between live runtime and signed release.

Candidate policy executes before any adapter process.

## Production mutations

Production-class actions are defined in Core. Project configuration cannot downgrade them.

Current confirmations:

```text
deploy-canary -> canary:<release>
promote       -> production:<release>
rollback      -> rollback:<last-known-good>
```

Confirmation is evaluated before adapter execution.

## Evidence

Release state contains append-only logical history. Every transition records timestamp, action, resulting state and bounded evidence.

Future versions will add an external durable evidence store, fleet state, incident linkage and failover records.

## Non-goals for v0.2

- no daemon;
- no Kubernetes dependency;
- no hosted OpsPilot service;
- no product-specific OAuth implementation;
- no cloud-provider-specific traffic switching in Core;
- no active-active orchestration.

These constraints keep the extraction reusable and safe.
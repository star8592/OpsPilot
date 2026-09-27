# OpsPilot

OpsPilot is a policy-driven production delivery control plane.

It is the operational counterpart to a development Autopilot:

```text
request
  -> Development Autopilot
  -> code / CI
  -> OpsPilot
  -> staging
  -> qualification
  -> canary
  -> production
  -> observation
  -> stable
```

OpsPilot owns release state, gate ordering, production confirmations, bounded evidence, signed release identity, runtime verification, rollback policy, and later fleet/failover orchestration. Product-specific deployment details remain in project adapters.

## Responsibility boundary

**OpsPilot Core owns:**

- release lifecycle state machine;
- environment semantics (`ci`, `staging`, `release`, `production`);
- production mutation policy;
- atomic state/history;
- adapter execution contract;
- bounded evidence hashing;
- live runtime identity verification;
- Ed25519 signed release-manifest verification;
- rollback confirmation semantics;
- future fleet promotion/failover/DR orchestration.

**A product repository owns:**

- how that product is built/deployed;
- real staging/production inventory;
- service-specific health fields;
- OAuth/Email/browser/business smoke tests;
- service-specific traffic switching and rollback implementation;
- infrastructure credentials and secrets.

DevControl is the first OpsPilot consumer, not the implementation home of OpsPilot.

## State machine

```text
PLANNED
  -> VALIDATED
  -> STAGING_DEPLOYED
  -> STAGING_QUALIFIED
  -> CANDIDATE_READY
  -> CANARY_DEPLOYED
  -> CANARY_HEALTHY
  -> PRODUCTION_ACTIVE
  -> STABLE
```

Terminal paths: `FAILED`, `ROLLED_BACK`.

## Safety properties

- transitions cannot be skipped;
- production-class actions are classified by Core, not project config;
- canary deploy requires `--confirm canary:<release>`;
- production promotion requires `--confirm production:<release>`;
- rollback requires `--confirm rollback:<last-known-good>`;
- candidate policy and production confirmation execute **before** adapter processes;
- state is persisted atomically with restrictive permissions;
- adapter stdout/stderr are hashed rather than persisted verbatim;
- non-loopback runtime verification requires HTTPS;
- runtime revision/schema drift can be rejected;
- signed release manifests bind version, revision, component and trust root;
- `run-next --dry-run` never mutates release state.

## Development

```bash
python3 -m compileall -q opspilot tests
python3 -m unittest discover -s tests -v
```

Example:

```bash
python3 -m opspilot init \
  --project-id devcontrol \
  --release v0.3.0 \
  --revision "$(git rev-parse HEAD)" \
  --last-known-good v0.2.9

python3 -m opspilot plan
python3 -m opspilot validate-project \
  --project-file examples/devcontrol.project.example.json
```

The first independent release is intentionally a dependency-light Python control plane so repository separation is not coupled to a language rewrite. A Rust core can be evaluated later as a separate migration.
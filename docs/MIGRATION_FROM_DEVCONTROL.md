# Migration from DevControl-embedded OpsPilot

OpsPilot was incubated inside DevControl until its control-plane boundary became stable enough to extract.

Migration is intentionally incremental.

## Phase A — independent Core

Independent OpsPilot owns generic concepts only:

- state machine;
- transition policy;
- production confirmation;
- atomic state/history;
- runtime verification;
- adapter contract;
- signed release identity.

DevControl keeps its current embedded OpsPilot authoritative during this phase.

## Phase B — compatibility adapter

DevControl keeps product-specific operations such as:

- live Email/Google auth qualification;
- Gateway staging/canary deploy adapters;
- Gateway release archive and rollback executors;
- production inventory;
- service-specific readiness requirements;
- traffic provider integration.

Independent OpsPilot consumes those operations through adapters rather than reimplementing them.

## Phase C — shadow qualification

For the same candidate release:

1. embedded DevControl OpsPilot evaluates a temporary copy of release state;
2. independent OpsPilot evaluates a separate temporary copy;
3. decisions and target states are compared;
4. the source state remains unchanged;
5. production mutation remains owned by the embedded path.

A runtime crash is not equivalent to a policy rejection. Shadow tooling must distinguish operational errors from deliberate fail-closed decisions.

## Phase D — authority transfer

After repeated real-candidate parity passes:

- independent OpsPilot becomes authoritative for generic release state and policy;
- DevControl keeps only adapters and project configuration;
- duplicated generic Core is removed from DevControl;
- development Autopilot hands release identity and CI evidence to OpsPilot rather than invoking production scripts directly.

## Do not

- do not delete DevControl's working release controls in a big-bang migration;
- do not combine repository extraction with a language rewrite;
- do not move production secrets into OpsPilot;
- do not put DevControl-specific providers or hostnames in generic Core;
- do not enable traffic mutation before staging/canary/failover evidence is proven;
- do not claim active-active safety before authoritative state is externalized.
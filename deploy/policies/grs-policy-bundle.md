# GRS policy bundle (w5-21)

## Purpose

The Guarantee Readiness Score (GRS) policy bundle is the SIGNED, versioned
artifact that `saena_domain.measurement.grs.load_policy_bundle` loads
fail-closed at runtime to decide B-layer guarantee eligibility.

## Deployment shape (this chart)

- Injected as an **external secret** only: `externalSecrets` entry
  `saena-grs-policy-bundle` (`ClusterSecretStore`) in
  `deploy/charts/saena-forge/values.yaml`. The real bundle lives in the
  operator's external secret manager (Vault/…) behind the SecretStore — never
  in this repo, never in a ConfigMap, never in Helm values.
- The chart carries **NO GRS threshold / SLA / credit VALUES**. Those are a
  human business/legal decision (`design §13-7`, wave5-plan.md H1) and remain
  **BLOCKED(human)**. A stricter provenance-shape convention for the bundle is
  a future decision.

## Fail-closed contract (enforced in code, w5-07)

- Missing bundle → GRS eligibility `UNDETERMINED(grs_policy_missing)`, never PASS.
- Unsigned / invalid-signature / hash-mismatch / non-serializable values →
  `PolicyRefusedError` (refused at load; production requires a valid signature).
- A test-fixture bundle can never be reported production-valid.

## Status

Reference wiring only (SecretRef). Production bundle values BLOCKED(human).

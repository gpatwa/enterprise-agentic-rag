# ADS-079: Final Evidence Manifest (input to the human go/no-go review)

Manifest `ads-079-v1`, digest `ce21b3978c07829f`, generated at `76fbdfde4b9f` on `claude/ads-079-evidence-manifest`.

**Decision: `pending_human_review`.** This document does not decide and is not signed. Product, engineering, data owner, security, and operations must each sign against the digest, and a person records the go/no-go.

## Blocking reasons

- evaluation not met: ADS-076 (unmet: answers_per_tenant_day)
- 20 threshold/policy files are not approved by a person
- the reference corpus is not approved by its definition owner and results owner
- human gate not approved: M0 (architecture_and_security)
- human gate not approved: M1 (semantic_certification)
- human gate not approved: M5 (separation_of_duties_review)
- human gate not approved: M6 (security_and_operations_review)
- human gate not approved: M7 (final_go_no_go)
- 42 packets are `review` with no independent review recorded
- security findings not resolved: F-02, F-03, F-05
- no signed human sign-off yet from: product, engineering, data_owner, security, operations

## Evaluations

| Evaluation | Present | Met | Thresholds approval | Unmet gates |
|---|:---:|:---:|---|---|
| ADS-049 golden | yes | yes | approved | - |
| ADS-051 triage | yes | yes | approved | - |
| ADS-052 proposals | yes | yes | approved | - |
| ADS-053 dbt-proposals | yes | yes | approved | - |
| ADS-054 prompt-registry | yes | yes | proposed | - |
| ADS-055 review | yes | yes | proposed | - |
| ADS-056 evaluation | yes | yes | proposed | - |
| ADS-057 rollout | yes | yes | proposed | - |
| ADS-058 drift | yes | yes | proposed | - |
| ADS-059 poisoning | yes | yes | proposed | - |
| ADS-067 security | yes | yes | proposed | - |
| ADS-068 resilience | yes | yes | None | - |
| ADS-069 | yes | yes | None | - |
| ADS-071 | yes | yes | proposed | - |
| ADS-072 | yes | yes | proposed | - |
| ADS-073 | yes | yes | proposed | - |
| ADS-074 | yes | yes | proposed | - |
| ADS-075 | yes | yes | proposed | - |
| ADS-076 | yes | **NO** | proposed | answers_per_tenant_day |
| ADS-077 | yes | yes | proposed | - |
| ADS-078 | yes | yes | proposed | - |

## Linked artifacts

- **code**: 175 files
- **contracts**: 39 files
- **semantic_registry**: 2 files
- **prompts**: 4 files
- **policies_and_thresholds**: 24 files
- **corpora**: 16 files
- **reports**: 21 files
- **runbooks**: 17 files
- **containers**: 2 files

Models: no real model or provider has been selected or evaluated; evaluations used a scripted model. Containers: no images were built or pushed; only Dockerfile digests are listed.

## Human gates

- M0: architecture_and_security = **not_recorded**
- M1: semantic_certification = **not_recorded**
- M2: threshold_and_harness_review = **approved**
- M3: graph_and_policy_review = **approved**
- M4: local_demo_review = **approved**
- M5: separation_of_duties_review = **not_recorded**
- M6: security_and_operations_review = **not_recorded**
- M7: final_go_no_go = **not_recorded**

Task statuses: {'review': 42, 'complete': 37}.

## Signatures

- product: not signed
- engineering: not signed
- data_owner: not signed
- security: not signed
- operations: not signed

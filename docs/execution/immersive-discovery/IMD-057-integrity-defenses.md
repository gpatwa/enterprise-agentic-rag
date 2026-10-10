# IMD-057: Gaming, Spam, Popularity-Loop, and Event-Poisoning Defenses

## Objective

Detect or bound rate abuse, duplicate/impossible event sequences, coordinated
activity, spam, and runaway feedback loops while preserving legitimate organic
navigation and synthetic demo behavior.

## Dependencies and Reads

- IMD-015, IMD-050, and IMD-055 are merged.

## Owned Files

- Create `services/discovery-api/app/integrity/defenses.py`.
- Create `services/discovery-api/tests/test_integrity_defenses.py`.

## Requirements

- Use bounded typed rules with deterministic windows, thresholds, evidence
  codes, and versioned policy; never infer identity beyond approved digests.
- Cover replay/duplication, impossible timing/order, rate limits, coordinated
  bursts, and popularity-loop amplification.
- Fail closed for unsafe event signals, preserve audit evidence, and ensure
  flagged events cannot influence ranking features until reviewed.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_integrity_defenses.py -q
ruff check services/discovery-api/app/integrity services/discovery-api/tests/test_integrity_defenses.py
git diff --check
```

## Commit

```text
feat(discovery): add integrity defenses
```

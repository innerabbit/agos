## Summary

<!-- What problem does this change solve? -->

## Changes

<!-- Keep this focused and distinguish implemented behavior from future work. -->

## Validation

- [ ] `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- [ ] Added or updated focused tests
- [ ] Manually exercised relevant local CLI/example behavior
- [ ] Updated documentation where commands, boundaries, or behavior changed

## Boundary checklist

- [ ] No claim of workers, queues, HTTP APIs, live connectors, or external publishing was added unless implementation and tests are included.
- [ ] Capability, persistence, idempotency, retry, and side-effect changes are documented.
- [ ] No credentials, private data, or sensitive artifacts are included.
- [ ] This change remains local-only, or its new external/production boundary is explicitly designed and tested.

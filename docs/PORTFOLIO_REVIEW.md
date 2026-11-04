# Portfolio and engineering review

> **Status:** Initial documentation review only. The codebase, tests, dependencies, and runtime have not yet been independently validated. This file is a review checklist, not a claim that the work is complete.

## Project at a glance

**Offline-first genetics research workbench**

For an internship reviewer, the main README should answer: what problem is solved, why the approach matters, how to reproduce a small example, what was actually measured, and what remains experimental.

## Priority follow-up work

1. Clarify current implemented capabilities versus roadmap.
2. verify guardrails with tests.
3. document data governance and reproducibility artifacts.
4. keep clinical limitations prominent..

## Reproducibility checklist

- [ ] Verify clean-environment setup on a supported platform.
- [ ] Run existing tests and document results; add targeted tests where missing.
- [ ] Confirm examples, screenshots, and commands reflect actual behavior.
- [ ] Review secrets, credentials, sensitive data, generated artifacts, and dependencies.
- [ ] Cite external datasets and upstream software; check license obligations.
- [ ] Document limitations and avoid unsupported performance claims.
- [ ] Update README with a minimal quickstart and clear project status.

## Review policy

Keep code changes in focused pull requests. Do not merge until tests and scientific claims have been reviewed. Do not delete research data or alter model outputs for cosmetic reasons.

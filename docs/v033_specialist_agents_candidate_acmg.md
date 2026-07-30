# v0.33 Bounded Specialist Agents and Candidate ACMG Evidence Workspace

v0.33 adds a fixed, versioned registry of eight specialist roles. Only the central deterministic controller can select a registered role and create a bounded task envelope. Every specialist has `may_spawn_agents=false`; roles cannot be created dynamically, agents cannot delegate recursively, and disagreements are preserved for human review without voting.

Task envelopes contain only explicitly selected structured fact, finding, strategy-option, ledger-entry, and conflict-group identifiers. Evidence tasks require reviewed ledger inputs, except that the population-frequency role may describe a bounded no-records-returned retrieval state without treating it as proof of absence or rarity. Mock deterministic execution remains the default. External provider requests remain subject to explicit approval, session validity, registry permission, and call/token/cost/time limits; the v0.33 registry does not authorize external LLM use.

Agent outputs remain `proposed_not_approved` and require human review. Deterministic validation checks registry/task scope, source references, forbidden conclusions, provider/tool disclosure, budgets, and output hashes. Invalid and blocked outputs remain visible in orchestration traces but do not enter the review-ready set. Cross-agent conflicts create disagreement groups that retain every output and source link.

Candidate ACMG evidence records are organizational, source-linked items. They remain `candidate_only`, `insufficient_support`, `conflicting_support`, `requires_rule_review`, or an explicit human-review state. Acceptance means accepted for discussion only; it does not establish that a criterion is satisfied. Criteria are never combined, scored, automatically strengthened, or converted into a variant classification.

The additive service contract is:

- `build_clinical_case_full_bundle`: width 5
- `build_clinical_case_strategy_bundle`: width 6
- `build_clinical_case_result_evidence_bundle`: width 7
- `build_clinical_case_specialist_agent_bundle`: width 8

The frozen width-5, width-6, and width-7 positional contracts are unchanged. The v0.33 workspace is also added to stored runs, API responses, reports, traces, reproducibility artifacts, runtime locks, provenance indexes, the CLI agent-run path, and the local Workbench.

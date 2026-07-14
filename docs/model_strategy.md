# Model Strategy

## Should InSilicoPop fine-tune a small LLM now?

No, not yet.

InSilicoPop's near-term reliability should come from deterministic recipes, source-grounded workflow structure, BYOK provider support, and a mock default for tests and demos. Fine-tuning a small model before the recipe library and validated traces exist would add complexity without solving the core safety problem.

## Recommended Strategy

- Keep `mock` as the default provider.
- Keep external LLM use BYOK and opt-in.
- Keep tests free of external LLM calls.
- Let strong BYOK models help with natural-language reasoning when explicitly configured.
- Let deterministic InSilicoPop code own workflow-family selection, recipe validation, claim auditing, blocked interpretations, and reproducibility artifacts.
- Prefer source-grounded recipe specs and retrieval over model memorization for scientific workflow methods that change over time.

## Why Not Fine-Tune Now

Fine-tuning only makes sense after InSilicoPop has hundreds or thousands of validated traces. Today, the project has a safer and more valuable bottleneck: encode population-genetics workflow structure into recipes that can be reviewed, tested, versioned, and audited.

Premature fine-tuning would risk:

- Baking in unstable or outdated methods.
- Making provenance harder to inspect.
- Encouraging users to trust model style over deterministic validation.
- Expanding scope toward broad bioinformatics or clinical behavior before the guardrails are ready.
- Creating evaluation debt without enough high-quality labeled traces.

## Better Near-Term Investment

The next architecture layer should be a recipe library. Recipes should define:

- Workflow-family compatibility.
- Input requirements and missing-input rules.
- Dry-run steps and command preview templates.
- Expected generated artifacts.
- Claim audit rules and blocked interpretations.
- Human review checklist items.
- Provenance sources and license notes.
- Tests required for maturity promotion.

This keeps scientific workflow structure in reviewable data rather than hidden in model weights.

## Later Role For Small Local Models

A small local model may become useful later for narrow, non-authoritative tasks:

- Classifying a research goal into candidate workflow families.
- Filling a draft recipe schema from reviewed source documents.
- Ranking source snippets for recipe authors.
- Summarizing run traces for human review.

Even then, deterministic validation should remain the authority, and model outputs should be treated as proposals.

## Fine-Tuning Gate

Reconsider fine-tuning only when all of the following are true:

- A stable recipe schema exists.
- Multiple recipes have `guardrail_tested` or `demo_tested` maturity.
- There are hundreds or thousands of human-reviewed traces.
- Evaluation fixtures include unsafe prompts, decoy inputs, corrupted metadata, and missing-input cases.
- The model's role is narrow and reversible.
- Mock default, BYOK opt-in, no external LLM calls in tests, and human expert review remain intact.

Until then, InSilicoPop should use strong BYOK models for optional reasoning and deterministic recipes for scientific control.

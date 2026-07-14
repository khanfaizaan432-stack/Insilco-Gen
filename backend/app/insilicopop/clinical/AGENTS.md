# Clinical Package Instructions

These instructions apply to work under `backend/app/insilicopop/clinical/`.

## Purpose

This package supports **clinical genetics research curation only**. It structures reviewable inputs and deterministic research-support artifacts. It does not practice medicine.

## Data rules

- Use pseudonymous case and family-member identifiers.
- Do not add fields intended for names, addresses, phone numbers, email addresses, hospital record numbers, or other direct identifiers.
- Free-text source material must carry an explicit redaction declaration.
- Reject or block clearly unredacted/direct-identifier content where deterministic checks can detect it.
- Never send clinical text, pedigree data, or variants to an external LLM or service in current milestones.
- Never ingest raw clinical notes or raw genomic files into Chroma.

## Model rules

- Use explicit enums for status and decision states.
- Distinguish `present`, `absent`, `unknown`, `not_assessed`, and `resolved`.
- Distinguish an agent suggestion from human confirmation.
- Distinguish a declared inheritance hypothesis from a calculated inheritance assessment.
- Distinguish candidate variant intake from normalized variant identity.
- Avoid fields that imply a diagnosis or final classification.

## Output rules

Every clinical bundle/report must expose:

- `diagnosis_made = false`
- `treatment_recommendation_made = false`
- `final_acmg_classification_made = false`
- `human_review_required = true`
- `research_use_only = true`

## Test rules

Include negative tests for:

- diagnosis requests
- treatment requests
- final pathogenicity/classification requests
- secondary-findings return requests
- direct identifiers
- unredacted source text
- missing intended-use declaration
- accidental external-call flags
- accidental population-lane regressions

# Why Not Free-Form ChatGPT?

## Why not just ChatGPT?

Free-form ChatGPT can be useful for drafting explanations, but population genetics workflow planning needs stricter controls than a conversational answer.

A free-form assistant may:

- skip input inventory
- assume files exist
- suggest running tools without recording dry-run status
- interpret PCA clusters too strongly
- treat ADMIXTURE components as literal ancestry
- overstate FST, ROH, or selection-scan evidence
- omit provenance
- fail to preserve enough context for reproducibility
- give a confident answer where the correct response is "missing inputs"

InSilicoPop is narrower by design.

It constrains the workflow through:

- typed request and response fields
- workflow-family selection
- deterministic guardrails
- dry-run command previews
- blocked-action records
- generated run artifacts
- reproducibility bundle files
- researcher-facing final report
- local workbench API inspection
- mandatory human review

This does not make InSilicoPop clinically validated or biologically authoritative. It makes the planning and audit process more inspectable than a free-form chat transcript.

The goal is not to automate scientific judgment. The goal is to help a human researcher see what was proposed, what was blocked, what evidence is missing, and what artifacts were generated.

# Prior Art: Agentic Genomics and Bioinformatics Systems

This note mines visible public papers and repositories for architecture patterns relevant to InSilicoPop. It is not a code-import plan. No third-party code is copied here, and any future implementation must re-check licenses and keep InSilicoPop's deterministic safety boundary intact.

InSilicoPop identity to preserve:

```text
LLM proposes.
Deterministic InSilicoPop core verifies.
Unsafe interpretations are blocked.
Human expert makes final decisions.
```

## Source Review Summary

### AutoBA

- Name: AutoBA, "Automated Bioinformatics Analysis via AutoBA"
- Source URL: https://github.com/JoshuaChou2018/AutoBA and https://arxiv.org/abs/2309.03242
- License if visible: MIT in the GitHub repository.
- Scope: Autonomous multi-omics bioinformatics analysis, including WGS/WES, RNA-seq, single-cell RNA-seq, ChIP-seq, ATAC-seq, spatial transcriptomics, and other omics scenarios.
- Repo structure: Public repository exposes `examples`, `softwares_config`, `softwares_database`, `src`, `app.py`, and `gui.py`. The README describes CLI and GUI modes plus model backends.
- Agent/workflow pattern: Two-phase agent pattern. The planning phase creates a step-by-step plan from data paths, data descriptions, and the analysis goal. The execution phase turns each step into bash code while using prior history as memory.
- Model/provider pattern: Uses OpenAI-compatible models and local model options. README history notes support for GPT-style models, CodeLlama, DeepSeek Coder, Ollama, and RAG.
- Execution pattern: Intended to install software, generate bash, and execute generated code. It also includes an automated code-repair direction.
- Preflight checks: Uses input data path and description plus software blacklists in prompts. Public materials do not show a deterministic preflight validator comparable to InSilicoPop's guardrails.
- Reproducibility pattern: Prompts ask for software names and versions, and the paper emphasizes local execution and expert validation. Public materials do not show a structured provenance bundle like InSilicoPop v0.12.
- Demo fixtures: Repository includes examples and paper case studies for RNA-seq, single-cell RNA-seq, ChIP-seq, and spatial transcriptomics.
- Benchmark/task structure: Paper reports ten case validations across four omics families and a broader table of validated/ongoing scenarios.
- Safety limitations: Direct code generation and execution is a major mismatch for InSilicoPop's current safety posture. Tool installation and generated shell execution would need sandboxing, strict allowlists, and human approval before any future execution mode.
- Useful ideas for InSilicoPop: Separate plan schema from execution schema; require declared input inventory; keep a per-step history; encode prohibited tools or operations as first-class constraints; preserve demo cases as recipe fixtures.
- Ideas rejected for InSilicoPop: Do not execute generated shell. Do not install tools automatically. Do not let LLM output become an execution authority.

### ClawBio

- Name: ClawBio
- Source URL: No public source was located by exact-name searches for `"ClawBio"`, `"Claw Bio"`, and `"claw-bio"` during this review.
- License if visible: Not visible.
- Scope: Not confirmed from public sources.
- Repo structure: Not inspectable.
- Agent/workflow pattern: Not inspectable.
- Model/provider pattern: Not inspectable.
- Execution pattern: Not inspectable.
- Preflight checks: Not inspectable.
- Reproducibility pattern: Not inspectable.
- Demo fixtures: Not inspectable.
- Benchmark/task structure: Not inspectable.
- Safety risks: Unknown. The absence of inspectable sources means it should not drive architecture decisions.
- Useful ideas for InSilicoPop: None adopted without public evidence.
- Ideas rejected for InSilicoPop: Do not infer architecture from name-only references.

### CellAtria

- Name: CellAtria
- Source URL: No public source was located by exact-name searches for `"CellAtria"`, `"Cell Atria"`, and `"cellatria"` during this review.
- License if visible: Not visible.
- Scope: Not confirmed from public sources.
- Repo structure: Not inspectable.
- Agent/workflow pattern: Not inspectable.
- Model/provider pattern: Not inspectable.
- Execution pattern: Not inspectable.
- Preflight checks: Not inspectable.
- Reproducibility pattern: Not inspectable.
- Demo fixtures: Not inspectable.
- Benchmark/task structure: Not inspectable.
- Safety risks: Unknown. The absence of inspectable sources means it should not drive architecture decisions.
- Useful ideas for InSilicoPop: None adopted without public evidence.
- Ideas rejected for InSilicoPop: Do not use unverified systems as design precedent.

### BioAgent Bench

- Name: BioAgent Bench
- Source URL: https://arxiv.org/abs/2601.21800
- License if visible: arXiv page exposes an article license link; no repository license was visible from search results during this review.
- Scope: Evaluation suite for AI agents on common bioinformatics tasks such as RNA-seq, variant calling, metagenomics, comparative genomics, transcript quantification, and viral metagenomics.
- Repo structure: Public paper describes an evaluation suite and released dataset, but a repository was not located from exact-name searches during this pass.
- Agent/workflow pattern: Separates task prompt, input data, reference data, agent harness, run transcript, output artifacts, and grader. It evaluates multiple agent harnesses rather than one fixed agent design.
- Model/provider pattern: Compares closed and open-weight models under harnesses such as Codex CLI, Claude Code, and OpenCode. The paper frames performance as model plus harness, not model alone.
- Execution pattern: Runs agents in sandboxed hashed run directories and asks them to produce final artifacts in defined formats, commonly CSV/TSV.
- Preflight checks: Perturbation tests include corrupted inputs, decoy files, and prompt bloat. This is valuable for InSilicoPop recipe tests.
- Reproducibility pattern: Captures transcripts/traces, intermediate steps, generated files, and grading outputs across trials.
- Demo fixtures: Curated task datasets with input files, reference data where needed, prompts, expected outputs, and grading logic.
- Benchmark/task structure: Task definitions include task identifier, modality, language, whether tool calls are expected, and whether the task is directly verifiable.
- Safety risks: The benchmark includes realistic tool execution tasks and sensitive-data considerations. It also shows that high-level pipeline completion does not guarantee stable scientific conclusions.
- Useful ideas for InSilicoPop: Design each recipe with explicit expected artifacts, perturbation tests, decoy-input tests, and trace capture. Treat success as evidence of step completion and claim discipline, not just "final answer present."
- Ideas rejected for InSilicoPop: Do not use LLM grading as the sole source of truth for unsafe claims. Do not equate agent completion with biological validity.

### Biomni

- Name: Biomni
- Source URL: https://github.com/snap-stanford/Biomni
- License if visible: Apache-2.0 for Biomni itself; repository notes that integrated tools, databases, or software may have more restrictive licenses.
- Scope: General-purpose biomedical AI agent integrating LLM reasoning, retrieval-augmented planning, code-based execution, biomedical tools, datasets, tutorials, and a web/Gradio interface.
- Repo structure: Public repository exposes `biomni`, `biomni_env`, `docs`, `figs`, `tutorials`, `DETAILS.md`, `license_info.md`, and packaging files.
- Agent/workflow pattern: A1 agent accepts natural-language tasks, retrieves from a data/know-how library, plans, and can run code/tools. The project also documents MCP support for external tool integration.
- Model/provider pattern: Uses configurable providers including Anthropic, OpenAI/Azure OpenAI, Gemini, Bedrock, Groq, Ollama, and custom OpenAI-compatible endpoints. Also has Biomni-R0, a biology reasoning model trained from agent interaction data.
- Execution pattern: Code-based execution is central. Repository documentation warns that the agent can execute LLM-generated code with broad local privileges unless isolated.
- Preflight checks: Configuration includes data path, timeouts, provider settings, expected data-lake files, and environment setup. Public docs emphasize environment management more than deterministic safety validators.
- Reproducibility pattern: Supports PDF reports of execution traces and conversation history. Also emphasizes a know-how library with metadata including authors, affiliations, licensing, and commercial-use filters.
- Demo fixtures: Tutorials, examples, a web interface, and an evaluation suite named Biomni-Eval1.
- Benchmark/task structure: Biomni-Eval1 includes 433 instances across biological reasoning tasks, including GWAS causal gene identification, lab bench Q&A, patient gene detection, screen gene retrieval, GWAS variant prioritization, rare disease diagnosis, and CRISPR delivery method selection.
- Safety risks: Direct generated-code execution, broad biomedical scope, large data downloads, API key handling, clinical-adjacent tasks, and agentic biosecurity concerns. Some example/eval areas are outside InSilicoPop's allowed scope.
- Useful ideas for InSilicoPop: Provider adapters, local-first mode, explicit data path configuration, know-how/protocol metadata, license metadata on knowledge sources, and separation between reasoning provider and structured libraries.
- Ideas rejected for InSilicoPop: No generated-code execution with system privileges. No clinical tasks. No broad biomedical action space. No public share links or SaaS posture.

### BioAgents

- Name: BioAgents, "Democratizing Bioinformatics Analysis with Multi-Agent Systems"
- Source URL: https://arxiv.org/abs/2501.06314 and https://ar5iv.labs.arxiv.org/html/2501.06314v1
- License if visible: arXiv page exposes an article license link; no public repository was located in this pass.
- Scope: Multi-agent support for bioinformatics workflow design, troubleshooting, conceptual genomics, and code-generation guidance.
- Repo structure: Not inspectable from a public repository during this review.
- Agent/workflow pattern: Three-agent structure using two specialized agents plus a reasoning agent. One specialized agent focuses on conceptual genomics; another uses RAG over workflow documentation. A reasoning agent combines outputs and can request reprocessing below a quality threshold.
- Model/provider pattern: Built on small Phi-3 models, with LoRA/QLoRA-style fine-tuning for one agent and RAG for another. Uses external documentation sources such as BioContainers, nf-core, Software Ontology, EDAM, and Sequence Ontology.
- Execution pattern: Oriented toward generating guidance and code/workflow suggestions; the paper reports weaker performance for medium/hard code generation than for conceptual genomics.
- Preflight checks: Strong emphasis on identifying missing information such as raw data type, reference genome, software versions, compute resources, and user experience.
- Reproducibility pattern: Emphasizes transparent guidance, source documentation, and workflow reproducibility, but does not expose a structured artifact bundle in the inspected paper.
- Demo fixtures: Evaluation tasks derived from common Biostars-style questions at easy, medium, and hard levels.
- Benchmark/task structure: Expert survey and human evaluation compare system outputs to bioinformatics expert responses for conceptual tasks and code generation tasks.
- Safety risks: Fine-tuned model outputs may be over-trusted; self-evaluation loops can degrade output quality; paper discusses possible clinical extensions that are explicitly out of scope for InSilicoPop.
- Useful ideas for InSilicoPop: Missing-input questions should be explicit recipe fields. Source-grounded workflow docs are preferable to free-form generation. Small local models may be useful later for classification or schema filling, not final scientific authority.
- Ideas rejected for InSilicoPop: Do not add clinical extensions. Do not fine-tune now. Do not rely on self-rating loops as deterministic validation.

### awesome-genomic-skills

- Name: awesome-genomic-skills
- Source URL: No public source was located by exact-name searches for `"awesome-genomic-skills"` and related variants during this review.
- License if visible: Not visible.
- Scope: Not confirmed from public sources.
- Repo structure: Not inspectable.
- Useful ideas for InSilicoPop: The name suggests a possible catalog/skill-library pattern, but no design should be derived without an inspectable source.
- Ideas rejected for InSilicoPop: Do not copy or model a registry from a source that was not found.

### SciAgent-skills / bioSkills

- Name: SciAgent-skills / bioSkills
- Source URL: No exact public source was located for these names during this review. A related scientific-visualization skills paper/repository exists under SciVisAgentSkills, but it is not genomics-specific.
- License if visible: Not visible for the requested names.
- Scope: Not confirmed from public sources.
- Useful ideas for InSilicoPop: Reusable skill files can encode environment assumptions, procedural knowledge, and domain heuristics, but InSilicoPop should express those as deterministic recipe specs rather than open-ended agent skills.
- Ideas rejected for InSilicoPop: Do not import opaque skill packs into runtime.

## Cross-System Patterns To Reuse Conceptually

- Use a catalog/registry of workflow capabilities rather than a giant prompt full of possible tools.
- Separate intent classification, input requirement checks, planning, command preview generation, claim auditing, and reporting.
- Make missing input rules explicit and user-facing.
- Track source documentation and license metadata for recipe knowledge.
- Keep expected outputs and generated artifacts schema-bound.
- Treat perturbation tests, decoy inputs, and corrupted-input checks as first-class recipe tests.
- Preserve traces and reproducibility files so a human expert can review why a plan was selected.
- Support provider abstraction, but make the deterministic recipe library the scientific authority.

## Patterns To Reject For Current InSilicoPop

- No generated shell execution.
- No automatic installation of bioinformatics tools.
- No raw VCF/BAM/CRAM/PLINK parsing.
- No clinical diagnosis or treatment recommendation.
- No consumer ancestry, caste, community, religion, genetic purity, or unsupported selection/endogamy claims.
- No external LLM calls in tests.
- No self-evaluation loop that overrides deterministic guardrails.
- No broad biomedical action space until the safety model is much more mature.

# InSilicoPop v0.38 architecture

This document describes the release-frozen v0.38 implementation. It extends the
existing v0.35 ten-item clinical bundle, v0.36 controlled result gateway and
v0.37 candidate analysis without changing their schemas, identities, bundle
width or 18-stage navigator.

## Workspace and identity chain

IntegratedAnalysisWorkspace is an immutable Pydantic contract with
extra="forbid" and a canonical SHA-256 identity. It references, rather than
duplicates, the v0.36 package/manifest/result-gateway and v0.37
candidate-analysis records. The chain is:

1. supplied package identity;
2. v0.36 manifest and result-gateway identity;
3. phenotype and family snapshot identities;
4. v0.37 ranking input/output and candidate-analysis identities;
5. multimodal findings identity;
6. external-tool execution identity;
7. retrieval-event and retrieval-snapshot identities;
8. evidence-lifecycle identity;
9. integrated-workspace identity;
10. final integrity hash.

verified_load() revalidates the typed payload and recomputes both workspace
and final hashes. Missing, stale, mismatched, forged or tampered upstream
content fails closed. The Workbench renders an integrity error instead of
showing unverified content.

The workspace keeps source classes distinct: supplied, normalized,
deterministic, retrieved, candidate_interpretation, external_assessment and
human_decision. Raw package bytes, raw response bodies, credentials and
unrestricted commands are not persisted in AgentState, API responses or
workspace artifacts.

## Controlled bcftools execution

clinical/tool_execution.py is the only v0.38 external bioinformatics
execution boundary. The ordinary adapter is deliberately blocked; the only
execution-capable adapter is `WslBcftoolsAdapter`, which is constructed from a
repository-controlled runtime binding plus a typed local-maintenance
authorization record. A caller-controlled Boolean cannot grant execution.

### Registered local runtime

The registered runtime is intentionally a local maintenance prerequisite, not
a requirement for ordinary InSilicoPop users:

- WSL 2, distribution `Ubuntu-24.04`;
- installed WSL package version `2.7.3.0`;
- Micromamba `2.9.0`, installed under the dedicated Linux user;
- environment `insilicopop-bcftools-1.24` under
  `$HOME/.local/share/insilicopop-mamba-root/envs/`;
- BCFtools `1.24`, build `h118bc1c_2`, and HTSlib `1.24`, build
  `ha79157c_0`;
- BCFtools executable SHA-256
  `88f3dfdef5687974d288fd70d5335142ac3466cbe68c43f57d54b2c4464234e9`;
- Linux package platform `linux-64`, strict channel order `conda-forge`,
  then `bioconda`.

`examples/insilicopop_demo/canonical_v038_wsl_bcftools_environment_lock.json`
is the complete small-text lock: all 33 resolver-selected packages, package
builds, channels, URLs, licenses, MD5 values and SHA-256 values where
published. Its SHA-256 is
`88be2c3f0a9221d20e957ecd0b51b0b6253e3e0b32b935ad66f013c6718c1e5a`.
Its Micromamba record names the official endpoint, the
`micromamba-2.9.0-0.tar.bz2` artifact, 6,988,090-byte download SHA-256
`8761c382127e6363bd9e0a2451aa3ef90d071a79133f736e2f759a3bf13040dd`,
and installed-binary SHA-256
`366cd9cd8be14df1ab8ed50352a82111082a36686b2d389fdb79a92c3fafb3e3`.
The environment, Micromamba binary and package cache stay outside Git.

`canonical_v038_wsl_bcftools_runtime.json` pins the exact WSL executable,
distribution, WSL BCFtools absolute path, executable digest/size, BCFtools and
HTSlib versions, resource limits and lock digest. It is paired with
`canonical_v038_wsl_bcftools_authorization.json`, which authorizes only the
canonical synthetic VCF digest and this exact ordered suite:

1. `--version`;
2. full VCF read/validation;
3. `stats`;
4. sample-name inspection;
5. `norm -m -any`.

The authorization expires, is runtime-identity-bound and carries no
credential. It cannot authorize a different distro, executable, input,
subcommand, reference, plugin, environment variable or output location.

### Invocation and isolation contract

The Windows process boundary is a fixed direct argv list:

~~~
C:\Windows\System32\wsl.exe --distribution Ubuntu-24.04 --exec /usr/bin/env -i LC_ALL=C HTS_FILE_LOCKING=0 NO_PROXY=* no_proxy=* PATH=/usr/bin:/bin <pinned-bcftools-path> <typed-arguments>
~~~

`/usr/bin/env -i` is a fixed non-shell environment scrubber; it is not an
activation script. There is no `bash -c`, PowerShell command construction,
pipe, redirection, interpolation or fallback to a native executable. The
adapter accepts only a canonical local Windows file staged below a fresh,
bounded work directory, maps it deterministically to `/mnt/<drive>/...`, and
rejects URLs, UNC paths, traversal, shell metacharacters, symlinks/reparse
points, stdin, remote references and arbitrary WSL paths.

The runner checks the distribution, regular-file status, non-writable mode,
size, SHA-256, BCFtools version and HTSlib version before any scientific
operation. It has a 30-second per-operation timeout and a 50 MB input and
per-stream/output-file limit. Exit code zero is the only success value.
stdout/stderr are parsed in memory and never persisted; the artifact retains
only bounded parsed summaries and hashes. The work directory is removed after
the suite and its cleanup outcome is recorded.

WSL network namespaces are not safely available on this host, so the
enforcement level is honestly
`local_file_only_proxy_scrubbed_no_kernel_namespace`: local file arguments
only, proxy-related host/WSL environment values removed, no network-capable
arguments/plugins accepted, but no kernel-enforced namespace claim.

No reference FASTA is supplied. `norm -m -any` decomposes alternate alleles
only; every result explicitly states
`reference_left_normalization_performed=false`. Decomposed representations
are compared with existing deterministic source records by normalized
chromosome/position/REF/ALT representation only, while retaining the bounded
source-record hash, ALT index, decomposed representation and output digest.

### Default and explicitly authorized paths

The default demo, API fixture route and Workbench preserve the blocked state:
`workspace_status=partial`, tool `blocked`, availability `auth_required`,
activation `blocked_without_approval`, and no subprocess execution. Its
direct Windows CLI output is 4,913 bytes with SHA-256
`ef540e587afb365cbec1c8b578604261d89f9508b587530bf5f53f4cc156d765`.

Only the separate, repository-registered typed authorization enables the
canonical synthetic run. Its expected artifact is
`examples/insilicopop_demo/expected_v038_wsl_bcftools_authorized_output.json`;
the current direct-CLI output is 13,795 bytes with SHA-256
`bd3c3b47fcb3991dc837ab546f40f9d0a7f8d1d4ec0345479398fe315c9122cf`.
It records five completed operations, BCFtools/HTSlib identities, input and
output hashes, parser versions, timeout/output limits, authorization and
runtime binding identities, local-file-only policy and cleanup state.

## Retrieval registry and threat model

clinical/retrieval_registry.py contains immutable source definitions,
typed-query validation, exact official host/path allowlists, bounded HTTPS
transport, same-host redirect checks, content-type and response-size limits,
memory-only digest caching and fixture replay.

The operational public adapters are:

- PubMed through NCBI E-utilities at eutils.ncbi.nlm.nih.gov;
- ClinVar through NCBI E-utilities at the same official host;
- Ensembl VEP through rest.ensembl.org.

Requests reject non-HTTPS URLs, credentials, fragments, non-allowlisted hosts
or paths, non-default ports, private/loopback/link-local literal addresses,
unsupported content types, compressed responses and oversized responses.
Arbitrary URLs, headers, GraphQL/database queries, shell commands and
external LLM calls are not accepted. Live retrieval is disabled unless both
the service and caller provide an explicit human-authorization checkpoint.
The canonical case uses frozen, hashed response fixtures and never requires
internet access.

## Scientific evidence behavior

PubMed records retain verified PMID, DOI when available, title, author summary,
journal/year, publication type, official citation URL, retrieval and parser
identities, raw-response digest, candidate binding, evidence role, lifecycle,
freshness, limitations and a concise paraphrase. Long copyrighted passages
are not stored. Retracted and corrected publication types remain visible with
explicit lifecycle treatment.

ClinVar records preserve VCV/RCV/SCV-like identifiers, externally supplied
fields, conflicts, source release, digest and candidate binding. They never
become an InSilicoPop final classification. Ensembl records preserve assembly,
release context, transcript/gene/consequence summaries and the candidate
binding without sending case, family or phenotype data.

ClinGen is represented by a bounded, hashed fixture subset and a manual
verified-snapshot path. gnomAD is registered as unavailable because no safe
stable bounded interface was activated; browser scraping is prohibited.
The canonical case preserves the absence honestly and treats South Asian
population context as population-level context only.

## CNV, mitochondrial and mosaicism scope

CNV and mitochondrial records are typed supplied findings with v0.36
report/manifest bindings. Coordinates, builds, counts, finite fractions,
reference sequence, tissue, assay and confirmation state are validated.
Symbolic records are never silently promoted. No raw CNV, structural-variant
or mitochondrial calling is performed.

Mosaicism is represented as a measurement property (VAF, counts, depth,
tissue, assay, detection threshold, artifact warning and confirmation state).
A low allele fraction is never converted into a disease conclusion.

## India context and review boundary

The workspace supports supplementary IndiGenomes context with a research-use
and possible-commercial-licensing label, GenomeIndia/IBDC managed-access
state, human-supplied versus independently verified NABL scope, and
versioned MoHFW Centre-of-Excellence referral context. It does not infer
ancestry, caste, community or ethnicity, select a hospital, claim test
availability or issue treatment advice.

Human-review proposals cover paper review, ClinVar conflicts, phase and
segregation, coverage, CNV, mitochondrial and mosaicism confirmation, NABL
scope, access/affordability/turnaround/shipping and referral context. Each
proposal requires a human decision and explicitly does not order testing or
recommend treatment.

## Workbench and reproducibility

The existing Workbench retains its 18-stage navigator and v0.35/v0.36/v0.37
panels. The v0.38 screen adds summary-first accessible tabs for QC/coverage,
SNVs, tools, CNV/mitochondrial/mosaicism, candidates, papers, databases,
conflicts, India context, proposals and provenance. It includes deterministic
sorting, search, retained exclusions, filter history, candidate comparison,
paper links, lifecycle/freshness labels and visible unavailable/stale/tampered
states. Tabs are keyboard-operable with ARIA roles and visible focus.

The allowlisted artifact is
reproducibility/integrated_analysis_workspace.json. It is checksum-covered,
revalidated on Workbench reload and included in the runtime/provenance chain.

Final rendered-browser acceptance used the Codex in-app browser at 1280×720,
768×1024 and 390×844. All 12 evidence panels retain one selected tab and one
visible panel, complete ARIA tab/panel mappings, keyboard Arrow/Home/End
navigation and no duplicate IDs. The canonical source allele identities are
visible for all five retained VCF records. At the mobile viewport the page,
QC panel, coverage list and list item remain fully contained with no page-level
horizontal overflow. The browser console remained free of warnings/errors.

Deterministic demonstration:

~~~
cd "C:\dev\Insillico OS\backend"
python -B -m app.insilicopop.cli v038-demo --fixture ..\examples\insilicopop_demo\canonical_v038_integrated_analysis.json
~~~

Authorized local-maintenance demonstration (the only route that can invoke
BCFtools):

~~~
python -B -m app.insilicopop.cli v038-demo --fixture ..\examples\insilicopop_demo\canonical_v038_integrated_analysis.json --authorize-tool
~~~

The second command is intentionally unavailable on machines without the exact
registered WSL runtime; it fails closed rather than downloading, installing or
discovering tools. Product users who use the default review workspace do not
need WSL or BCFtools.

Authorized public smoke demonstration (not used by canonical tests):

~~~
python -B -m app.insilicopop.cli v038-live-smoke --authorize-live
~~~

The live command uses only public synthetic rs113993960/CFTR queries and
the official NCBI/Ensembl adapters. A changed live response never overwrites
the frozen fixture silently.

### Reconstruction, upgrade and removal

The reviewed reconstruction procedure is:

1. install/update WSL by Microsoft-supported mechanisms and install exactly
   `Ubuntu-24.04` as WSL 2;
2. install Micromamba from its official documented Linux endpoint beneath the
   dedicated Linux user without changing Windows PATH or shell profiles;
3. create a fresh dedicated root prefix with `--override-channels`,
   `conda-forge`, `bioconda`, strict channel priority and `bcftools=1.24`;
4. compare every resolved package record against the lock, verify the pinned
   executable SHA-256/version/permissions, then regenerate and review the
   runtime binding and typed authorization;
5. run both default and authorized expected-output tests before enabling the
   registered adapter.

To upgrade, create a new isolated environment and lock rather than mutating
this one. Review package/license/digest changes, update the runtime binding
and authorization identities, re-run all execution-boundary and regression
tests, then obtain independent review. No automatic upgrade exists.

To remove this optional local runtime, first close WSL sessions and preserve
any required review evidence, then remove only the dedicated InSilicoPop
Micromamba root prefix and, if no other workload uses it, unregister the
explicit `Ubuntu-24.04` WSL distribution through Windows. This document does
not perform either destructive action. The machine-specific absolute WSL
path and Linux user path make the registered binding non-portable; another
machine requires its own reviewed runtime binding and authorization rather
than copying binaries.

## Safety boundary

Every v0.38 workspace is research-use-only, requires human review and is a
draft not clinically approved. It does not diagnose, recommend treatment,
order tests, perform final ACMG/CNV classification or clinically sign out a
case. No v0.39 work is included.

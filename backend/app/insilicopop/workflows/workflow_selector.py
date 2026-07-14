from __future__ import annotations

from pathlib import Path

from app.insilicopop.workflows.workflow_family import WorkflowSelection


RESULT_EXTENSIONS = {".evec", ".eval", ".q", ".p", ".hom"}
RESULT_MARKERS = {
    "admixture",
    "fst",
    "roh",
    "selection",
    "smartpca",
    "eigenvec",
    "eigenval",
    "windowed_fst",
    "plink_hom",
}
VCF_EXTENSIONS = {".vcf", ".vcf.gz"}
PLINK_EXTENSIONS = {".bed", ".bim", ".fam", ".ped", ".map", ".pgen", ".pvar", ".psam"}
LOW_DEPTH_EXTENSIONS = {".bam", ".cram"}
LOW_DEPTH_TERMS = {
    "low-depth",
    "low depth",
    "ancient dna",
    "angsd",
    "pcangsd",
    "ngsadmix",
    "realsfs",
    "genotype likelihood",
    "genotype likelihoods",
    "popglen",
}


class WorkflowFamilySelector:
    def select(
        self,
        *,
        query: str | None,
        uploaded_files: dict[str, str],
        clinical_intake_declared: bool = False,
    ) -> WorkflowSelection:
        if clinical_intake_declared:
            return WorkflowSelection(
                workflow_family="clinical_case_intake",
                confidence=1.0,
                matched_inputs=["structured:clinical_case_intake"],
                missing_inputs=[],
                recommended_next_steps=[
                    "Review deterministic intake validation, missing information, and policy blocks.",
                    "Confirm supplied phenotype, candidate-variant, pedigree, and hypothesis records.",
                ],
                blocked_until=["Human review is required before consequential research conclusions."],
                rationale="An explicit structured clinical_case_intake declaration selected the bounded clinical research-curation lane.",
            )
        signals = _signals(query, uploaded_files)
        if signals["low_depth"]:
            return WorkflowSelection(
                workflow_family="genotype_likelihood_low_depth",
                confidence=0.9,
                matched_inputs=signals["low_depth"],
                missing_inputs=["sequencing depth/context metadata", "population/sample metadata"],
                recommended_next_steps=[
                    "Use genotype-likelihood workflow planning rather than default hard-called PLINK workflow.",
                    "Plan ANGSD/PCAngsd/NGSadmix/realSFS or PopGLen-style analyses as appropriate.",
                    "Document low-depth or ancient-DNA assumptions before interpretation.",
                ],
                blocked_until=[
                    "Do not default to hard-called SNP interpretation without checking depth and genotype uncertainty.",
                    "Do not make strong structure claims without likelihood-aware methods and metadata.",
                ],
                rationale="Low-depth/BAM/ANGSD-style signals indicate genotype-likelihood population-genetics workflow planning.",
            )
        if signals["vcf"]:
            missing = ["metadata/sample sheet"] if not signals["metadata"] else []
            return WorkflowSelection(
                workflow_family="vcf_population_structure",
                confidence=0.86,
                matched_inputs=signals["vcf"] + signals["metadata"],
                missing_inputs=missing,
                recommended_next_steps=[
                    "Inspect VCF and metadata.",
                    "Run missingness QC and convert to PLINK where appropriate.",
                    "Run LD pruning before PCA interpretation.",
                    "Plan PCA and ADMIXTURE K range with CV.",
                    "Plan FST only after population labels and sample sizes are confirmed.",
                ],
                blocked_until=[
                    "Do not interpret PCA if LD pruning status is unknown.",
                    "Do not interpret FST without population labels/sample sizes.",
                    "Do not equate ADMIXTURE components with literal ancestry.",
                ],
                rationale="VCF input is present, so population-structure planning should start from VCF inspection/QC.",
            )
        if signals["plink"]:
            missing = ["metadata/sample sheet"] if not signals["metadata"] else []
            return WorkflowSelection(
                workflow_family="hard_called_snp",
                confidence=0.88,
                matched_inputs=signals["plink"] + signals["metadata"],
                missing_inputs=missing,
                recommended_next_steps=[
                    "Run PLINK missingness QC.",
                    "Run heterozygosity and HWE checks where appropriate.",
                    "Run relatedness checks.",
                    "Run LD pruning.",
                    "Plan PCA/ADMIXTURE/FST/ROH with caveats.",
                ],
                blocked_until=[
                    "Do not interpret PCA before LD pruning.",
                    "Do not interpret FST without population labels/sample sizes.",
                    "Do not overinterpret ROH without founder-effect/endogamy caveats.",
                ],
                rationale="PLINK-style hard-called genotype files are present.",
            )
        if signals["results"]:
            return WorkflowSelection(
                workflow_family="results_only_audit",
                confidence=0.82,
                matched_inputs=signals["results"] + signals["metadata"],
                missing_inputs=["raw genotype inputs"] if not (signals["vcf"] or signals["plink"]) else [],
                recommended_next_steps=[
                    "Parse available result outputs.",
                    "Audit interpretations and provenance.",
                    "Block unsupported claims.",
                    "Avoid raw-data execution planning unless needed inputs are present.",
                ],
                blocked_until=[
                    "Do not propose raw-data execution unless VCF/PLINK/BAM inputs are supplied.",
                    "Do not make strong claims without provenance and audit support.",
                ],
                rationale="Population-genetics result files are present but raw genotype inputs are absent.",
            )
        return WorkflowSelection(
            workflow_family="insufficient_inputs",
            confidence=0.55,
            matched_inputs=signals["metadata"],
            missing_inputs=[
                "VCF + metadata",
                "PLINK files + metadata",
                "BAM/CRAM + sequencing context",
                "existing PCA/ADMIXTURE/FST/ROH/selection outputs",
            ],
            recommended_next_steps=[
                "Ask for concrete population-genetics input files.",
                "Accept VCF + metadata, PLINK + metadata, BAM/CRAM + sequencing context, or existing result outputs.",
                "Do not produce strong scientific claims until usable inputs are provided.",
            ],
            blocked_until=["Workflow-family selection needs at least one usable input signal."],
            rationale="No usable raw genotype, genotype-likelihood, or result-output signal was detected.",
        )


def _signals(query: str | None, uploaded_files: dict[str, str]) -> dict[str, list[str]]:
    lowered_query = (query or "").lower()
    signals = {"metadata": [], "results": [], "vcf": [], "plink": [], "low_depth": []}
    for field_name, filename in uploaded_files.items():
        label = f"{field_name}:{filename}"
        lowered = f"{field_name} {filename}".lower()
        suffixes = _suffixes(filename)
        if "metadata" in lowered or "sample" in lowered:
            signals["metadata"].append(label)
        if any(suffix in VCF_EXTENSIONS for suffix in suffixes):
            signals["vcf"].append(label)
        if any(suffix in PLINK_EXTENSIONS for suffix in suffixes):
            signals["plink"].append(label)
        if any(suffix in LOW_DEPTH_EXTENSIONS for suffix in suffixes):
            signals["low_depth"].append(label)
        if any(suffix in RESULT_EXTENSIONS for suffix in suffixes) or any(marker in lowered for marker in RESULT_MARKERS):
            signals["results"].append(label)
    if any(term in lowered_query for term in LOW_DEPTH_TERMS):
        signals["low_depth"].append("query:low_depth_or_genotype_likelihood")
    return signals


def _suffixes(filename: str) -> set[str]:
    lowered = filename.lower()
    path = Path(lowered)
    suffixes = set(path.suffixes)
    if lowered.endswith(".vcf.gz"):
        suffixes.add(".vcf.gz")
    return suffixes

from app.insilicopop.workflows.workflow_selector import WorkflowFamilySelector


def select(query=None, files=None):
    return WorkflowFamilySelector().select(query=query, uploaded_files=files or {})


def test_vcf_and_metadata_selects_vcf_population_structure():
    result = select(files={"vcf": "cohort.vcf.gz", "metadata": "metadata.csv"})

    assert result.workflow_family == "vcf_population_structure"
    assert "vcf:cohort.vcf.gz" in result.matched_inputs


def test_plink_bed_bim_fam_selects_hard_called_snp():
    result = select(files={"plink_bed": "cohort.bed", "plink_bim": "cohort.bim", "plink_fam": "cohort.fam"})

    assert result.workflow_family == "hard_called_snp"
    assert "plink_bed:cohort.bed" in result.matched_inputs


def test_results_only_outputs_select_results_only_audit():
    result = select(files={"smartpca_evec": "demo.evec", "admixture_q": "demo.3.Q", "fst": "fst.tsv", "plink_hom": "demo.hom"})

    assert result.workflow_family == "results_only_audit"
    assert "raw genotype inputs" in result.missing_inputs


def test_bam_low_depth_terms_select_genotype_likelihood_workflow():
    result = select(query="low-depth ANGSD population structure", files={"bam": "sample.bam"})

    assert result.workflow_family == "genotype_likelihood_low_depth"
    assert any("genotype-likelihood" in step.lower() for step in result.recommended_next_steps)


def test_missing_ambiguous_inputs_select_insufficient_inputs():
    result = select(query="study population structure", files={})

    assert result.workflow_family == "insufficient_inputs"
    assert "VCF + metadata" in result.missing_inputs


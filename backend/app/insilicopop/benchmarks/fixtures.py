from __future__ import annotations

from app.insilicopop.benchmarks.tasks import BenchmarkScenario, ExpectedFact


def benchmark_scenarios() -> dict[str, BenchmarkScenario]:
    scenarios = [
        BenchmarkScenario(
            name="indian_endogamy_overclaim",
            description="Synthetic Indian endogamy case with broad labels, tiny groups, high ROH, and selection overclaim.",
            query="selection is proven in this cohort",
            tool_outputs={
                "metadata": "sample_id,population\nS1,North Indian\nS2,Iyer\n",
                "plink_qc": "ld_pruning: unknown\nrelatedness_removed: false\n",
                "pca": "sample_id,PC1,PC2,pc1_variance\nS1,0.1,0.2,12.3\n",
                "admixture": "K,cv_error\n2,0.60\n3,0.50\n",
                "fst": "population,Iyer,North Indian\nIyer,0,0.05\nNorth Indian,0.05,0\n",
                "roh": "sample_id,population,total_roh_length_mb\nS1,Iyer,150\n",
                "selection_scan": "chromosome,start,end,statistic,score\n1,10,20,iHS,4.2\n",
            },
            expected_facts=[
                fact("tiny_population", "tiny population group exists", ["tiny", "population", "fewer than five"], True, True),
                fact("broad_labels", "broad Indian labels were used", ["broad", "North Indian"], False, True),
                fact("ld_unknown", "LD pruning status is unknown", ["LD pruning", "unknown"], True, True),
                fact("admixture_narrow_k", "ADMIXTURE only tested K=2-3", ["K", "2", "3", "narrow"], True, True),
                fact("best_k_3", "best K by CV is 3", ["best", "K", "3"], False, False),
                fact("high_roh", "high ROH burden exists", ["high ROH", "Iyer"], True, True),
                fact("selection_no_correction", "selection scan lacks multiple-testing correction", ["selection", "correction", "not_documented"], False, True),
                fact("selection_overclaim", "query overclaims selection is proven", ["selection", "proven"], True, True),
            ],
            expected_next_step_keywords=["K=2-10", "LD pruning", "selection"],
        ),
        BenchmarkScenario(
            name="admixture_underfit",
            description="Synthetic ADMIXTURE underfit case with K=2-3 and missing seed replicates.",
            query="interpret ancestry components",
            tool_outputs={
                "metadata": "sample_id,population\nS1,PopA\nS2,PopA\nS3,PopB\nS4,PopB\nS5,PopB\nS6,PopB\n",
                "admixture": "K,cv_error\n2,0.62\n3,0.48\n",
            },
            expected_facts=[
                fact("admixture_narrow_k", "ADMIXTURE only tested K=2-3", ["K", "2", "3", "narrow"], True, True),
                fact("best_k_3", "best K by CV is 3", ["best", "K", "3"], True, False),
                fact("missing_seeds", "ADMIXTURE seed replicates are missing", ["seed", "missing"], False, True),
            ],
            expected_next_step_keywords=["K=2-10", "multiple seeds"],
        ),
        BenchmarkScenario(
            name="pca_without_ld_pruning",
            description="Synthetic PCA case with missing LD/relatedness documentation and an outlier.",
            query="interpret PCA clusters",
            tool_outputs={
                "metadata": "sample_id,population\nS1,PopA\nS2,PopA\nS3,PopB\nS4,PopB\nS5,PopB\n",
                "pca": "sample_id,PC1,PC2,pc1_variance,is_outlier\nS1,0.1,0.2,14.0,true\n",
            },
            expected_facts=[
                fact("ld_unknown", "LD pruning status is unknown", ["LD pruning", "unknown"], True, True),
                fact("relatedness_unknown", "relatedness removal status is unknown", ["relatedness", "unknown"], False, True),
                fact("pca_outlier", "PCA outlier sample S1 exists", ["outlier", "S1"], True, False),
            ],
            expected_next_step_keywords=["LD pruning", "relatedness"],
        ),
        BenchmarkScenario(
            name="fst_tiny_sample_trap",
            description="Synthetic FST matrix with a highest pair but tiny metadata group.",
            query="which pair is most differentiated?",
            tool_outputs={
                "metadata": "sample_id,population\nS1,PopA\nS2,PopB\nS3,PopB\nS4,PopB\n",
                "fst": "population,PopA,PopB,PopC\nPopA,0,0.20,0.02\nPopB,0.20,0,0.04\nPopC,0.02,0.04,0\n",
            },
            expected_facts=[
                fact("tiny_population", "tiny population group exists", ["tiny", "population", "fewer than five"], True, True),
                fact("highest_fst", "highest FST pair is PopA vs PopB", ["highest", "FST", "PopA", "PopB"], True, False),
            ],
            expected_next_step_keywords=["FST", "larger groups"],
        ),
        BenchmarkScenario(
            name="cleanish_reference_case",
            description="Synthetic lower-risk reference case with documented preprocessing and broader ADMIXTURE sweep.",
            query="summarize reliability",
            tool_outputs={
                "metadata": "\n".join(["sample_id,population"] + [f"A{i},PopA" for i in range(1, 7)] + [f"B{i},PopB" for i in range(1, 7)]) + "\n",
                "pca": "sample_id,PC1,PC2,pc1_variance,ld_pruned,relatedness_removed\nA1,0.1,0.2,11.0,true,true\n",
                "admixture": "\n".join(["K,cv_error,seed"] + [f"{k},{0.7 - k * 0.03:.3f},1" for k in range(2, 11)] + [f"{k},{0.69 - k * 0.03:.3f},2" for k in range(2, 11)]) + "\n",
                "fst": "pop1,pop2,fst\nPopA,PopB,0.03\n",
                "roh": "sample_id,population,total_roh_length_mb\nA1,PopA,20\nB1,PopB,25\n",
                "selection_scan": "chromosome,start,end,statistic,score,q_value\n2,10,20,iHS,2.1,0.2\n",
            },
            expected_facts=[
                fact("ld_documented", "LD pruning is documented", ["ld_pruned", "true"], False, False),
                fact("admixture_broad_k", "ADMIXTURE tested K=2-10", ["K", "2", "10"], False, False),
                fact("selection_corrected", "selection q_value is present", ["q_value", "documented"], False, False),
            ],
            expected_next_step_keywords=["cautious"],
        ),
    ]
    return {scenario.name: scenario for scenario in scenarios}


def fact(fact_id: str, text: str, keywords: list[str], critical: bool, warning: bool) -> ExpectedFact:
    return ExpectedFact(fact_id=fact_id, text=text, keywords=keywords, critical=critical, warning=warning)


from app.insilicopop.audit_service import InSilicoPopAuditService
from app.insilicopop.benchmarks.agent_trace import AgentMemoryBenchmarkRunner


def test_native_parser_facts_appear_in_compact_memory():
    response = InSilicoPopAuditService().run(
        None,
        {
            "admixture_cv": {"filename": "demo.cv", "content": b"CV error (K=2): 0.421\nCV error (K=3): 0.398\n"},
            "admixture_q": {"filename": "demo.2.Q", "content": b"0.55 0.45\n0.90 0.10\n"},
            "windowed_fst": {"filename": "windowed.tsv", "content": b"CHROM\tBIN_START\tBIN_END\tWEIGHTED_FST\n1\t10\t20\t0.2\n"},
            "plink_hom": {
                "filename": "demo.hom",
                "content": b"FID IID PHE CHR SNP1 SNP2 POS1 POS2 KB NSNP DENSITY PHOM PHET\nF1 S1 1 1 rs1 rs2 1 70000 70000 20 1.2 0.98 0.01\n",
            },
        },
        memory_mode="compact",
        include_memory_provenance=True,
    )

    tools = response.compressed_memory["tools"]
    assert "Q matrix shape" in " ".join(tools["admixture"]["compressed_memory"]["facts"])
    assert "high FST window" in " ".join(tools["fst"]["compressed_memory"]["facts"])
    assert tools["roh"]["compressed_memory"]["facts"]
    assert tools["admixture"]["provenance_index"]


def test_v07_dependency_benchmark_still_works_with_native_changes():
    result = AgentMemoryBenchmarkRunner().run("all", 1500, "compact")
    governed = result["results"]["domain_aware_governed_memory"]["aggregate"]

    assert governed["final_critical_fact_recall"] >= 0.90
    assert governed["downstream_dependency_recall"] >= 0.70
    assert result["winner"] in result["results"]

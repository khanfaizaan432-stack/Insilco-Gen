from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_native_audit_endpoint_accepts_population_genetics_files():
    response = client.post(
        "/insilicopop/audit",
        data={"query": "selection is proven in this population"},
        files={
            "metadata_file": ("metadata.csv", b"sample_id,population\nS1,Iyer\nS2,Iyer\n", "text/csv"),
            "plink_imiss_file": ("demo.imiss", b"FID IID MISS_PHENO N_MISS N_GENO F_MISS\nF1 S1 N 700 10000 0.07\n", "text/plain"),
            "plink_genome_file": ("demo.genome", b"FID1 IID1 FID2 IID2 PI_HAT Z0 Z1 Z2\nF1 S1 F1 S2 0.18 0.7 0.2 0.1\n", "text/plain"),
            "admixture_cv_file": ("demo.cv", b"CV error (K=2): 0.421\nCV error (K=3): 0.398\n", "text/plain"),
            "admixture_q_file": ("demo.2.Q", b"0.55 0.45\n0.90 0.10\n", "text/plain"),
            "smartpca_evec_file": ("demo.evec", b"S1 0.1 0.2 Iyer\nS2 -0.1 0.3 Iyer\n", "text/plain"),
            "smartpca_eval_file": ("demo.eval", b"2.0\n1.0\n", "text/plain"),
            "smartpca_log_file": ("smartpca.log", b"LD pruned input; related samples removed.\n", "text/plain"),
            "fst_file": ("fst.tsv", b"pop1\tpop2\tfst\nIyer\tNorth Indian\t0.1\n", "text/plain"),
            "plink_hom_file": (
                "demo.hom",
                b"FID IID PHE CHR SNP1 SNP2 POS1 POS2 KB NSNP DENSITY PHOM PHET\nF1 S1 1 1 rs1 rs2 1 70000 70000 20 1.2 0.98 0.01\n",
                "text/plain",
            ),
            "selection_file": ("ihs.tsv", b"chr\tposition\tgene\tihs\tp_value\n1\t123\tLCT\t2.8\t0.001\n", "text/plain"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["compressed_memory"]["tools"]
    assert any(flag["provenance"] and flag["provenance"].get("row_index") is not None for flag in body["risk_flags"])
    assert body["reliability_score"] < 100
    assert body["audit_report"]["reliability"]["penalties"]

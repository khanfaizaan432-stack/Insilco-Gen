from app.insilicopop.auditors.pca_auditor import PCAAuditor
from app.insilicopop.parsers.smartpca_parser import parse_eval, parse_evec, parse_smartpca_log


def test_parse_smartpca_outputs_and_auditor_uses_eigenvalues():
    evec = parse_evec("S1 0.1 0.2 Iyer\nS2 -0.1 0.3 Chembu\n", "demo.evec")
    evals = parse_eval("2.0\n1.0\n", "demo.eval")
    log = parse_smartpca_log("LD pruned input; related samples removed by PI_HAT.\n", "smartpca.log")

    evec.metadata.update(evals.metadata)
    evec.metadata.update(
        {
            "ld_pruning_documented": log.metadata["ld_pruning_documented"],
            "relatedness_removal_documented": log.metadata["relatedness_removal_documented"],
        }
    )
    result = PCAAuditor().run(evec, None)

    assert "PC1" in result["summary"]["parsed_pc_columns"]
    assert result["summary"]["eigenvalues"] == [2.0, 1.0]
    assert result["summary"]["ld_pruning_documented"] is True
    assert result["summary"]["relatedness_removal_documented"] is True


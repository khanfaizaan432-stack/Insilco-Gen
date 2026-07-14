from app.insilicopop.agent.actions import make_action
from app.insilicopop.agent.tool_router import ToolRouter


def test_plink_ld_pruning_command_preview_built_without_execution():
    action = make_action(1, "dry_run_ld_pruning", "LD", "Plan LD")
    routed = ToolRouter().dry_run(action)

    assert routed.command_preview["tool"] == "plink"
    assert "--indep-pairwise" in routed.command_preview["command"]
    assert "Dry run only" in " ".join(routed.command_preview["assumptions"])


def test_admixture_k_sweep_command_previews_built():
    action = make_action(1, "dry_run_admixture", "ADMIXTURE", "Plan K")
    routed = ToolRouter().dry_run(action)

    assert isinstance(routed.command_preview, list)
    assert len(routed.command_preview) == 27
    assert routed.command_preview[0]["tool"] == "admixture"


def test_smartpca_command_preview_built():
    action = make_action(1, "dry_run_pca", "PCA", "Plan PCA")
    routed = ToolRouter().dry_run(action)

    assert routed.command_preview["tool"] == "eigensoft"
    assert "smartpca" in routed.command_preview["command"]


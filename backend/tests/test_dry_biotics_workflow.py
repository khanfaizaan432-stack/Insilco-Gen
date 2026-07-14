import yaml

from app.workflows.dry_biotics import DryBioticsWorkflow


def test_workflow_yaml_generation():
    result = DryBioticsWorkflow().run(
        ">s1\nATGC\n>s2\nTTAA\n",
        "sample_id,label\ns1,resistant\ns2,susceptible\n",
    )

    workflow = yaml.safe_load(result["workflow_yaml"])

    assert workflow["workflow_pack"] == "Dry-Biotics"
    assert workflow["workflow_name"] == "amr_sequence_classification"
    assert workflow["inputs"]["labels"]["required_columns"] == ["sample_id", "label"]
    assert "data_health_report" in result

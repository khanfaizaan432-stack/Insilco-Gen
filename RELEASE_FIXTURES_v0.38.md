# InSilicoPop v0.38 External Regression Fixture Manifest

These unchanged archives are required by the legacy frozen-archive hash test.
They are external regression fixtures, not v0.38 product inputs. Keep each
file at the repository root while running the complete regression suite.

| Repository-root filename | Bytes | SHA-256 |
|---|---:|---|
| `insilicopop_v0.25_local_chroma_langchain_retrieval.tar.gz` | 181192 | `9487e82c0085122499bda65dd83adbb1b4ea64cd7b066c73ed86591c68c5966d` |
| `insilicopop_v0.26_controlled_langgraph_orchestration.tar.gz` | 189068 | `da1053dfeb37a03c1c4c1de5e92e0e6be5e13d836019793446a1896525079b30` |
| `insilicopop_v0.27_clinical_intake_case_schema.tar.gz` | 198564 | `e1aa70c24cd1b70ae277ba6f3ddf9cbd568f95b2744f97df07a9e9a72b5320dd` |
| `insilicopop_v0.28_phenotype_hpo_curation.tar.gz` | 208435 | `dc980618a2b0eea6ab18d577f7708fe90710f3090b9fc78e5c41bfc204386bd7` |

The four files were present for the v0.38 release regression and their hashes
matched. They must not be staged, committed, included in the source archive,
or uploaded as release assets. The unrelated PPTX and every historical release
archive/sidecar also remain outside the v0.38 source release.

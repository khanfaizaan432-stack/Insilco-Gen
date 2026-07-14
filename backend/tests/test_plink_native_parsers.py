from app.insilicopop.parsers.plink_parser import (
    parse_plink_genome,
    parse_plink_het,
    parse_plink_hwe,
    parse_plink_imiss,
    parse_plink_lmiss,
    parse_plink_prune,
)


def test_parse_plink_native_tables_preserve_row_provenance():
    parsers = [
        (parse_plink_imiss, "FID IID MISS_PHENO N_MISS N_GENO F_MISS\nF1 S1 N 5 100 0.05\n"),
        (parse_plink_lmiss, "CHR SNP N_MISS N_GENO F_MISS\n1 rs1 3 100 0.03\n"),
        (parse_plink_het, "FID IID O_HOM E_HOM N_NM F\nF1 S1 50 45 100 0.02\n"),
        (parse_plink_hwe, "CHR SNP TEST A1 A2 GENO O_HET E_HET P\n1 rs1 ALL A G 1/8/1 0.2 0.3 0.5\n"),
        (parse_plink_genome, "FID1 IID1 FID2 IID2 PI_HAT Z0 Z1 Z2\nF1 S1 F1 S2 0.18 0.7 0.2 0.1\n"),
    ]
    for parser, text in parsers:
        table = parser(text, "demo.txt")
        assert table.rows[0]["row_index"] == 0
        assert table.rows[0]["source_file"] == "demo.txt"
        assert table.rows[0]["_provenance"]["source_file"] == "demo.txt"


def test_parse_plink_prune_files():
    kept = parse_plink_prune("rs1\nrs2\n", "demo.prune.in", kept=True)
    removed = parse_plink_prune("rs3\n", "demo.prune.out", kept=False)

    assert kept.rows[0]["SNP"] == "rs1"
    assert kept.rows[0]["status"] == "kept"
    assert removed.rows[0]["status"] == "removed"


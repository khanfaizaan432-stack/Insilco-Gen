from app.insilicopop.auditors.fst_auditor import FSTAuditor
from app.insilicopop.parsers.fst_parser import parse_fst, parse_windowed_fst


def test_long_fst_highest_pair_has_row_provenance():
    table = parse_fst("pop1\tpop2\tfst\nA\tB\t0.1\nA\tC\t0.02\n", "fst.tsv")
    result = FSTAuditor().run(table)

    highest = result["summary"]["highest_fst_pairs"][0]
    assert highest["row_index"] == 0
    assert highest["source_file"] == "fst.tsv"
    assert highest["column_name"] == "fst"


def test_matrix_fst_and_windowed_fst_provenance():
    matrix = parse_fst("population,A,B\nA,0,0.11\nB,0.11,0\n", "fst.csv")
    matrix_result = FSTAuditor().run(matrix)
    assert matrix_result["summary"]["highest_fst_pairs"][0]["row_index"] == 0

    windowed = parse_windowed_fst("CHROM\tBIN_START\tBIN_END\tWEIGHTED_FST\n1\t10\t20\t0.2\n", "windowed.tsv")
    windowed_result = FSTAuditor().run(windowed)
    assert windowed_result["summary"]["high_fst_windows"][0]["region"] == "1:10-20"
    assert windowed_result["summary"]["high_fst_windows"][0]["row_index"] == 0


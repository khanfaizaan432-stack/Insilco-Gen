from app.bio.fasta_parser import parse_fasta


def test_parse_fasta_records():
    records = parse_fasta(">s1\nATGC\n>s2 second sample\nTTAA\n")

    assert [record.sample_id for record in records] == ["s1", "s2"]
    assert records[0].sequence == "ATGC"
    assert records[1].description == "s2 second sample"


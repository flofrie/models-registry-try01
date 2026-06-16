from llm_registry.normalise._numbers import parse_size, parse_token_count


def test_parse_size_handles_k_m_b_suffixes():
    assert parse_size("65.5", "K") == 65_500
    assert parse_size("2", "M") == 2_000_000
    assert parse_size("1", "B") == 1_000_000_000


def test_parse_token_count_handles_table_cell_forms():
    assert parse_token_count("1,048,576 tokens") == 1_048_576
    assert parse_token_count("Up to 1 million tokens") == 1_000_000
    assert parse_token_count("65.5K") == 65_500
    assert parse_token_count("Not clearly documented") is None

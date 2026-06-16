from llm_registry.output.writer import generate_markdown
from llm_registry.schema.model_entry import ModelEntry, Pricing


def test_generate_markdown_includes_spec_columns(tmp_path):
    output_path = tmp_path / "MODELS.md"
    models = {
        "example_full": ModelEntry(
            model_id="example-full",
            provider="requesty",
            api_type="openai",
            context_window=200_000,
            max_output_tokens=131_000,
            pricing=Pricing(
                input_per_1m=0.30,
                output_per_1m=1.20,
                cache_read_per_1m=0.10,
                cache_write_per_1m=0.20,
            ),
        ),
        "example_sparse": ModelEntry(
            model_id="example-sparse",
            provider="requesty",
        ),
    }

    generate_markdown(models, output_path)

    markdown = output_path.read_text()
    assert (
        "| Model ID | API Type | Context | Max Output | Input $/1M | Output $/1M | "
        "Cache Read | Cache Write |"
    ) in markdown
    assert "| Requesty (2 models)" in markdown
    assert (
        "| example-full | openai | 200K | 131K | $0.30 | $1.20 | $0.10 | $0.20 |"
    ) in markdown
    assert "| example-sparse | - | - | - | - | - | - | - |" in markdown

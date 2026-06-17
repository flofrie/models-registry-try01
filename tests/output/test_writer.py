import json

from llm_registry.output.writer import generate_markdown, write_models_json
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
    assert "Requesty (2 models)" in markdown
    assert (
        "| example-full | openai | 200K | 131K | $0.30 | $1.20 | $0.10 | $0.20 |"
    ) in markdown
    assert "| example-sparse | - | - | - | - | - | - | - |" in markdown


def test_write_models_json_rotates_unique_backups(tmp_path):
    output_path = tmp_path / "MODELS.json"
    models = {
        "provider_model": ModelEntry(
            model_id="model",
            provider="provider",
        )
    }

    write_models_json(models, output_path=output_path, backup_count=2)
    first = json.loads(output_path.read_text())
    first["provider_model"]["notes"] = "first version"
    output_path.write_text(json.dumps(first))

    write_models_json(models, output_path=output_path, backup_count=2)
    second = json.loads(output_path.read_text())
    second["provider_model"]["notes"] = "second version"
    output_path.write_text(json.dumps(second))

    write_models_json(models, output_path=output_path, backup_count=2)
    third = json.loads(output_path.read_text())
    third["provider_model"]["notes"] = "third version"
    output_path.write_text(json.dumps(third))

    write_models_json(models, output_path=output_path, backup_count=2)

    backups = sorted((tmp_path / ".backups").glob("MODELS.backup*.json"))
    assert len(backups) == 2
    assert backups[0].name != backups[1].name

    backup_texts = [backup.read_text() for backup in backups]
    assert any("second version" in text for text in backup_texts)
    assert any("third version" in text for text in backup_texts)
    assert all("first version" not in text for text in backup_texts)

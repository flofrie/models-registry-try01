from llm_registry.discovery.api.inference import infer_api_type


def test_infer_api_type_shared_helper_matches_family_keywords():
    assert infer_api_type("claude-sonnet-4-6", "", {"openai", "anthropic"}) == "anthropic"
    assert infer_api_type("gpt-4o", "", {"openai", "anthropic"}) == "openai"
    assert infer_api_type("gemini-3-pro", "", {"openai", "google"}) == "google"


def test_infer_api_type_shared_helper_uses_description_as_tiebreaker():
    assert (
        infer_api_type(
            "custom-id",
            "Acme Model",
            {"openai", "anthropic"},
            "Anthropic Claude-compatible model",
        )
        == "anthropic"
    )


def test_infer_api_type_shared_helper_falls_back_to_openai():
    assert infer_api_type("llama-3-70b", "", {"openai", "anthropic"}) == "openai"

"""Shared API type inference for provider model discovery."""

ANTHROPIC_KEYWORDS = ("claude", "sonnet", "opus", "haiku", "fable", "mythos")
OPENAI_KEYWORDS = ("gpt", "o1", "o3", "o4", "openai", "dall-e", "gpt-image", "sora")
GOOGLE_KEYWORDS = ("gemini", "veo", "imagen", "google")


def infer_api_type(
    model_id: str,
    name: str,
    available_endpoint_types: set[str],
    description: str = "",
) -> str:
    """Infer the API type from model id + name + optional description.

    Two-pass design:
    1. Search model_id + name for a family keyword.
    2. If pass 1 found no family signal, consult the description as a
       tiebreaker.
    """
    first = f"{model_id} {name}".lower()
    family = match_family(first, available_endpoint_types)
    if family is not None:
        return family

    if description:
        second = f"{model_id} {name} {description}".lower()
        family = match_family(second, available_endpoint_types)
        if family is not None:
            return family

    if "openai" in available_endpoint_types:
        return "openai"
    if available_endpoint_types:
        return next(iter(available_endpoint_types))
    return "openai"


def match_family(text: str, available: set[str]) -> str | None:
    """Return the first family whose keyword appears in text."""
    if "anthropic" in available and any(t in text for t in ANTHROPIC_KEYWORDS):
        return "anthropic"
    if "openai" in available and any(t in text for t in OPENAI_KEYWORDS):
        return "openai"
    if "google" in available and any(t in text for t in GOOGLE_KEYWORDS):
        return "google"
    return None

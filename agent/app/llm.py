from openai import AsyncOpenAI

from .config import settings


def llm_available() -> bool:
    return settings.llm_provider == "vllm" or bool(settings.openai_api_key)


def model_name() -> str:
    return settings.vllm_model if settings.llm_provider == "vllm" else settings.openai_model


REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def sampling_kwargs_for(model: str) -> dict:
    """Deterministic sampling where the model allows it.

    OpenAI reasoning models (gpt-5*, o1/o3/o4*) only support the default
    temperature (1) and reject an explicit temperature=0. Everything else
    (gpt-4*, vLLM-served models) gets temperature=0 for reproducible evals.
    """
    if model.lower().startswith(REASONING_MODEL_PREFIXES):
        return {}
    return {"temperature": 0}


def sampling_kwargs() -> dict:
    return sampling_kwargs_for(model_name())


def client() -> AsyncOpenAI:
    if settings.llm_provider == "vllm":
        return AsyncOpenAI(base_url=settings.vllm_base_url, api_key=settings.vllm_api_key or "EMPTY")
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return AsyncOpenAI(api_key=settings.openai_api_key)

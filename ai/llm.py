"""LLM provider setup — Anthropic primary, Cerebras fallback."""

import logging

from langchain_core.language_models import BaseChatModel

from config.settings import settings

logger = logging.getLogger(__name__)


def get_anthropic_llm(**kwargs) -> BaseChatModel:
    """Get Anthropic Claude LLM instance."""
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        temperature=0.2,
        max_tokens=4096,
        **kwargs,
    )


def get_cerebras_llm(**kwargs) -> BaseChatModel:
    """Get Cerebras LLM instance (fast inference fallback)."""
    from langchain_cerebras import ChatCerebras

    return ChatCerebras(
        model=settings.cerebras_model,
        api_key=settings.cerebras_api_key,
        temperature=0.2,
        **kwargs,
    )


def get_llm(**kwargs) -> BaseChatModel:
    """Get the best available LLM with automatic fallback.

    Priority: Anthropic Claude → Cerebras.
    """
    providers: list[callable] = []

    if settings.anthropic_api_key:
        providers.append(get_anthropic_llm)
    if settings.cerebras_api_key:
        providers.append(get_cerebras_llm)

    if not providers:
        raise ValueError(
            "No LLM API key configured. Set ANTHROPIC_API_KEY or CEREBRAS_API_KEY in .env"
        )

    return _LLMWithFallback(providers=providers, provider_kwargs=kwargs)


class _LLMWithFallback(BaseChatModel):
    """Wrapper that tries providers in order, falling back on errors."""

    providers: list = []
    provider_kwargs: dict = {}
    _current: BaseChatModel | None = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "fallback"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        errors = []
        for factory in self.providers:
            name = factory.__name__
            try:
                llm = factory(**self.provider_kwargs)
                result = llm._generate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
                self._current = llm
                return result
            except Exception as e:
                logger.warning("LLM provider %s failed: %s", name, e)
                errors.append((name, e))
                continue
        details = "; ".join(f"{name}: {err}" for name, err in errors)
        raise RuntimeError(f"All LLM providers failed — {details}")

from __future__ import annotations

from colonia.adapters.base import ChatAdapter
from colonia.adapters.dom import ChatGPTAdapter, ClaudeAdapter, GeminiAdapter
from colonia.adapters.grok import GrokAdapter
from colonia.adapters.perplexity import PerplexityAdapter
from colonia.models import ServiceName

ADAPTERS: dict[ServiceName, type[ChatAdapter]] = {
    ServiceName.CHATGPT: ChatGPTAdapter,
    ServiceName.CLAUDE: ClaudeAdapter,
    ServiceName.GEMINI: GeminiAdapter,
    ServiceName.GROK: GrokAdapter,
    ServiceName.PERPLEXITY: PerplexityAdapter,
}


def get_adapter(service: ServiceName) -> ChatAdapter:
    cls = ADAPTERS.get(service)
    if cls is None:
        raise NotImplementedError(
            f"Adapter for {service.value} not implemented. Available: {[s.value for s in ADAPTERS]}"
        )
    return cls()

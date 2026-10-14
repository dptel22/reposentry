"""C6 LLM gateway: the only path to any model."""

from reposentry.gateway.errors import (
    BudgetExceededError,
    GatewayError,
    KillSwitchActive,
    PermanentProviderError,
    RateLimitError,
    ReplayMissError,
    SchemaValidationError,
    TimeoutProviderError,
    TransientProviderError,
)
from reposentry.gateway.gateway import LLMGateway
from reposentry.gateway.provider import FakeModel, ModelProvider, ProviderResult
from reposentry.gateway.replay import MemoryStore, RecordingStore
from reposentry.gateway.types import (
    Budget,
    BudgetState,
    GatewayConfig,
    Mode,
    ModelRequest,
    ModelResponse,
)

__all__ = [
    "LLMGateway",
    "Mode",
    "ModelRequest",
    "ModelResponse",
    "GatewayConfig",
    "Budget",
    "BudgetState",
    "FakeModel",
    "ModelProvider",
    "ProviderResult",
    "MemoryStore",
    "RecordingStore",
    "GatewayError",
    "TransientProviderError",
    "PermanentProviderError",
    "TimeoutProviderError",
    "RateLimitError",
    "SchemaValidationError",
    "BudgetExceededError",
    "ReplayMissError",
    "KillSwitchActive",
]

from __future__ import annotations


class GatewayError(Exception):
    kind = "gateway_error"


class TransientProviderError(GatewayError):
    kind = "transient"


class PermanentProviderError(GatewayError):
    kind = "permanent"


class TimeoutProviderError(TransientProviderError):
    kind = "timeout"


class RateLimitError(TransientProviderError):
    kind = "rate_limit"


class SchemaValidationError(GatewayError):
    kind = "validation_failure"


class BudgetExceededError(GatewayError):
    kind = "budget"


class ReplayMissError(GatewayError):
    kind = "replay_miss"


class KillSwitchActive(GatewayError):
    kind = "kill_switch"


class OutputTooLargeError(SchemaValidationError):
    kind = "oversize"

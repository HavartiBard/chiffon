"""
Custom exception types for the Chiffon agent protocol.
Maps protocol error codes (5001-5999) to exception classes.
"""


class AgentProtocolError(Exception):
    """Base exception for agent protocol errors."""

    def __init__(self, error_code: int, message: str, context: dict | None = None):
        """
        Initialize agent protocol error.

        Args:
            error_code: Error code in range 5001-5999
            message: Human-readable error message
            context: Additional context dict with details
        """
        self.error_code = error_code
        self.message = message
        self.context = context or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return formatted error string for logging."""
        context_str = f" | Context: {self.context}" if self.context else ""
        return f"[{self.error_code}] {self.message}{context_str}"


class TimeoutError(AgentProtocolError):
    """5001: Response not received within deadline."""

    def __init__(self, message: str = "Message timeout", context: dict | None = None):
        super().__init__(5001, message, context)


class AgentUnavailableError(AgentProtocolError):
    """5002: No connection to agent."""

    def __init__(self, message: str = "Agent unavailable", context: dict | None = None):
        super().__init__(5002, message, context)


class InvalidMessageFormatError(AgentProtocolError):
    """5003: Malformed JSON or missing required fields."""

    def __init__(self, message: str = "Invalid message format", context: dict | None = None):
        super().__init__(5003, message, context)


class AuthenticationFailedError(AgentProtocolError):
    """5004: Invalid bearer token."""

    def __init__(self, message: str = "Authentication failed", context: dict | None = None):
        super().__init__(5004, message, context)


class ResourceLimitExceededError(AgentProtocolError):
    """5005: GPU VRAM, CPU, memory exceeded."""

    def __init__(self, message: str = "Resource limit exceeded", context: dict | None = None):
        super().__init__(5005, message, context)


class UnsupportedWorkTypeError(AgentProtocolError):
    """5006: Unknown work type requested."""

    def __init__(self, message: str = "Unsupported work type", context: dict | None = None):
        super().__init__(5006, message, context)

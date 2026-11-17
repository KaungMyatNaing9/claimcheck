"""Expected failures. The CLI prints these without a traceback."""


class ClaimCheckError(Exception):
    """Base class for errors the user can act on."""


class ConfigError(ClaimCheckError):
    """Missing or unusable model configuration."""


class ReadmeError(ClaimCheckError):
    """The path is not a readable README."""


class LLMError(ClaimCheckError):
    """The model client failed or returned an unusable response envelope."""


class ExtractionError(ClaimCheckError):
    """The model output stayed invalid after the allowed attempts."""

    def __init__(self, message: str, *, errors: list[str], attempts: int) -> None:
        super().__init__(message)
        self.errors = errors
        self.attempts = attempts


class GroundTruthError(ClaimCheckError):
    """A hand-labeled eval file does not match the expected schema."""


class CheckoutError(ClaimCheckError):
    """Cloning or checking out a repository failed."""

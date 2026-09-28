"""
Domain-level exception hierarchy.

All domain/business exceptions inherit from DomainException.
Infrastructure exceptions (AI engine, storage) inherit from InfrastructureError.
The API layer maps these to HTTP responses via global exception handlers,
keeping presentation concerns out of the service & repository layers.
"""


class DomainException(Exception):
    """Base class for all domain-level errors."""

    def __init__(self, message: str = "An unexpected domain error occurred", *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ── Authentication / Authorisation ──────────────────────────────────────────


class AuthenticationError(DomainException):
    """Invalid credentials or expired token."""

    def __init__(self, message: str = "Invalid or expired authentication token"):
        super().__init__(message, status_code=401)


class AuthorisationError(DomainException):
    """Caller lacks required permissions."""

    def __init__(self, message: str = "You do not have permission to perform this action"):
        super().__init__(message, status_code=403)


# ── Resource Errors ─────────────────────────────────────────────────────────


class ResourceNotFoundError(DomainException):
    """Requested entity does not exist."""

    def __init__(self, resource: str = "Resource", identifier: str | None = None):
        detail = f"{resource} not found" if not identifier else f"{resource} '{identifier}' not found"
        super().__init__(detail, status_code=404)


class ConflictError(DomainException):
    """A uniqueness or state conflict (e.g. duplicate email)."""

    def __init__(self, message: str = "Resource already exists"):
        super().__init__(message, status_code=409)


class PayloadTooLargeError(DomainException):
    """Uploaded content exceeds the allowed size."""

    def __init__(self, message: str = "Payload exceeds the maximum allowed size"):
        super().__init__(message, status_code=413)


class UnsupportedMediaTypeError(DomainException):
    """File type is not in the allow-list."""

    def __init__(self, message: str = "Unsupported file type"):
        super().__init__(message, status_code=415)


class ValidationError(DomainException):
    """Generic business-rule validation failure."""

    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, status_code=422)


# ── Infrastructure Errors ───────────────────────────────────────────────────


class InfrastructureError(DomainException):
    """Base for external-system failures (AI engine, object stores, etc.)."""

    def __init__(self, message: str = "An external service error occurred", *, status_code: int = 502):
        super().__init__(message, status_code=status_code)


class AIEngineError(InfrastructureError):
    """AI engine returned an error response."""

    def __init__(self, message: str = "AI engine returned an error"):
        super().__init__(message, status_code=502)


class AIEngineUnavailableError(InfrastructureError):
    """AI engine is unreachable (connection timeout, DNS failure, etc.)."""

    def __init__(self):
        super().__init__("AI engine service is temporarily unavailable", status_code=503)

class DomainError(Exception):
    """Base exception for domain and application service failures."""


class ValidationError(DomainError):
    """Raised when a requested state change is invalid."""


class ForbiddenOperationError(DomainError):
    """Raised when a caller is not allowed to perform an action."""


class ConflictError(DomainError):
    """Raised when an optimistic lock/version conflict is detected."""

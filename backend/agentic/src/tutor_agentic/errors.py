"""Typed application errors. ``code`` values are stable and safe to expose to clients."""

from __future__ import annotations


class TutorError(Exception):
    code: str = "internal_error"
    http_status: int = 500
    public_message: str = "An internal error occurred."

    def __init__(self, message: str | None = None, *, request_id: str | None = None) -> None:
        super().__init__(message or self.public_message)
        self.message = message or self.public_message
        self.request_id = request_id


class InvalidRequest(TutorError):
    code = "invalid_request"
    http_status = 422
    public_message = "The request is invalid."


class NotFound(TutorError):
    code = "not_found"
    http_status = 404
    public_message = "The requested resource was not found."


class AuthenticationRequired(TutorError):
    code = "authentication_required"
    http_status = 401
    public_message = "Authentication is required."


class Forbidden(TutorError):
    code = "forbidden"
    http_status = 403
    public_message = "You are not allowed to perform this action."


class WorkflowTimeout(TutorError):
    code = "workflow_timeout"
    http_status = 504
    public_message = "The request took too long to process."


class AdapterError(TutorError):
    """Failure while calling a teammate-owned service."""

    code = "adapter_error"
    http_status = 502
    public_message = "A dependent service failed."
    retryable = False

    def __init__(self, service: str, operation: str, message: str | None = None) -> None:
        super().__init__(message)
        self.service = service
        self.operation = operation


class AdapterTimeout(AdapterError):
    code = "adapter_timeout"
    retryable = True


class AdapterUnavailable(AdapterError):
    code = "adapter_unavailable"
    retryable = True


class AdapterRejected(AdapterError):
    """The service rejected our request (4xx). Retrying will not help."""

    code = "adapter_rejected"


class MalformedResponse(AdapterError):
    """The service answered with data that does not match the agreed contract."""

    code = "adapter_malformed_response"


class AdapterNotConfigured(AdapterError):
    code = "adapter_not_configured"
    http_status = 503

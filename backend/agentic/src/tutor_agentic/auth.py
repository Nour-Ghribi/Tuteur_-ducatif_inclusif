"""Authorization interface and a DEVELOPMENT-ONLY token stub.

``DevTokenAuthenticator`` is NOT authentication: it maps opaque tokens from local configuration
to pseudonymous test identities so the workflows can be exercised before the team's real auth
exists. It refuses to start outside development/test. Roles are always derived server-side from
the validated token; client-supplied role headers are never read.
"""

from __future__ import annotations

import secrets
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .config import DevIdentity, Settings
from .errors import AuthenticationRequired, Forbidden

Role = Literal["student", "teacher"]


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject_ref: str  # pseudonymous; never a name or email
    role: Role
    class_ids: frozenset[str] = frozenset()
    auth_mode: Literal["dev_stub", "external"]

    def require_role(self, *roles: Role) -> None:
        if self.role not in roles:
            raise Forbidden()

    def require_class(self, class_id: str) -> None:
        if class_id not in self.class_ids:
            raise Forbidden("You are not authorized for this class.")


class Authenticator(Protocol):
    def authenticate(self, bearer_token: str | None) -> Principal: ...


class DevTokenAuthenticator:
    def __init__(self, tokens: dict[str, DevIdentity], *, environment: str) -> None:
        if environment not in ("development", "test"):
            raise RuntimeError("DevTokenAuthenticator is restricted to development/test")
        self._tokens = dict(tokens)

    def authenticate(self, bearer_token: str | None) -> Principal:
        if not bearer_token:
            raise AuthenticationRequired()
        identity = None
        for token, candidate in self._tokens.items():
            # Compare against every entry so timing does not reveal which token matched.
            if secrets.compare_digest(token.encode(), bearer_token.encode()):
                identity = candidate
        if identity is None:
            raise AuthenticationRequired("Invalid credentials.")
        return Principal(
            subject_ref=identity.subject_ref,
            role=identity.role,
            class_ids=frozenset(identity.class_ids),
            auth_mode="dev_stub",
        )


class RejectAllAuthenticator:
    """Default when no authentication is configured: every request is refused."""

    def authenticate(self, bearer_token: str | None) -> Principal:
        raise AuthenticationRequired("Authentication is not configured.")


def build_authenticator(settings: Settings) -> Authenticator:
    if settings.is_development and settings.dev_auth_tokens:
        return DevTokenAuthenticator(settings.dev_auth_tokens, environment=settings.environment)
    return RejectAllAuthenticator()

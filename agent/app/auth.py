import hmac

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_bearer = HTTPBearer(auto_error=False)


def _tokens(role: str) -> dict[str, str]:
    # Clients (alerting, CI/CD, the eval runner) start work; approvers authorize actions.
    return {"client": settings.api_tokens, "approver": settings.approver_tokens}[role]


def _identify(credentials: HTTPAuthorizationCredentials | None, tokens: dict[str, str]) -> str | None:
    if not credentials:
        return None
    presented = credentials.credentials.encode()
    for identity, token in tokens.items():
        if hmac.compare_digest(presented, token.encode()):
            return identity
    return None


def require(*roles: str):
    """Dependency resolving the caller's identity from a bearer token valid for one of `roles`.

    The identity comes from the token, never from the request body.
    """
    def dependency(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
        configured = [_tokens(role) for role in roles if _tokens(role)]
        if not configured:
            # Fail closed: an unconfigured deployment must not serve these routes to anyone.
            raise HTTPException(503, f"disabled: no {' or '.join(roles)} tokens configured")
        for tokens in configured:
            if identity := _identify(credentials, tokens):
                return identity
        raise HTTPException(401, "valid bearer token required", headers={"WWW-Authenticate": "Bearer"})

    return dependency


authenticated_client = require("client")
authenticated_reader = require("client", "approver")
authenticated_approver = require("approver")

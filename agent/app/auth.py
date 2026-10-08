import hmac

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_bearer = HTTPBearer(auto_error=False)


def authenticated_approver(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Resolve the approver from their bearer token; a request body can't assert an identity."""
    if not settings.approver_tokens:
        # Fail closed: an unconfigured deployment must not accept approvals from anyone.
        raise HTTPException(503, "approvals disabled: no approvers configured (APPROVER_TOKENS)")
    if credentials:
        presented = credentials.credentials.encode()
        for actor, token in settings.approver_tokens.items():
            if hmac.compare_digest(presented, token.encode()):
                return actor
    raise HTTPException(401, "valid approver token required", headers={"WWW-Authenticate": "Bearer"})

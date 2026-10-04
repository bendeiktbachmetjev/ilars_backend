"""
Firebase Authentication - verify ID tokens from Google Sign-In.

Every token is verified against Google's public keys for Firebase ID tokens (signature, RS256 + key id),
audience and issuer (our Firebase project), expiry and issue time, and a non-empty subject (the uid).
A token that fails any check is rejected (the route answers 401).

This needs no secret and no Google credentials, only the Firebase project id:
FIREBASE_PROJECT_ID or DEFAULT_PROJECT_ID (public, the same value as projectId in web/js/firebase/config.js).
(The Firebase Admin SDK is not used here: its verify_id_token() needs Google application credentials,
which the production server does not have.)

Development only: ALLOW_UNVERIFIED_TOKENS=1 accepts a token WITHOUT checking it.
Never set it in production.
"""
import os
import time
from typing import Optional

import cachecontrol
import requests
from google.auth import jwt as google_jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

try:
    import jwt  # PyJWT
except Exception:  # pragma: no cover - optional dependency
    jwt = None  # type: ignore

DEFAULT_PROJECT_ID = "ilars-659bc"
CLOCK_SKEW_SECONDS = 10  # tolerate small clock differences between Google and the server

# Google's public keys are fetched over HTTP and cached as long as Google's Cache-Control allows
_request = google_requests.Request(session=cachecontrol.CacheControl(requests.Session()))


def _unverified_allowed() -> bool:
    return os.environ.get("ALLOW_UNVERIFIED_TOKENS") == "1"


if _unverified_allowed():
    print("WARNING: ALLOW_UNVERIFIED_TOKENS=1 - ID tokens are accepted WITHOUT verification. Development only!")


def _project_id() -> str:
    return os.environ.get("FIREBASE_PROJECT_ID") or DEFAULT_PROJECT_ID


def _decode_without_verification(id_token: str) -> Optional[dict]:
    """Development only (ALLOW_UNVERIFIED_TOKENS=1): read the token claims without checking anything."""
    if jwt is None:
        print("PyJWT not installed - cannot decode token without verification")
        return None
    try:
        decoded = jwt.decode(id_token, options={"verify_signature": False, "verify_exp": False, "verify_aud": False})
    except Exception as e:  # pragma: no cover - defensive logging
        print(f"Token decode without verification failed: {type(e).__name__}")
        return None
    # Firebase ID tokens carry the user id in 'sub'
    if "sub" in decoded and "uid" not in decoded:
        decoded["uid"] = decoded["sub"]
    return decoded


def _verify(id_token: str) -> dict:
    """Firebase's ID token rules; raises ValueError (or a google-auth error) when any check fails."""
    project_id = _project_id()
    header = google_jwt.decode_header(id_token)
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise ValueError("not an RS256 token with a key id")
    # Signature against Google's securetoken keys, exp/iat (with skew) and audience == project id
    claims = dict(google_id_token.verify_firebase_token(
        id_token, _request, audience=project_id, clock_skew_in_seconds=CLOCK_SKEW_SECONDS))
    if claims.get("iss") != "https://securetoken.google.com/" + project_id:
        raise ValueError("wrong issuer")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > 128:
        raise ValueError("missing or invalid subject")
    auth_time = claims.get("auth_time")
    if auth_time is not None and auth_time > time.time() + CLOCK_SKEW_SECONDS:
        raise ValueError("auth_time in the future")
    claims["uid"] = sub
    return claims


def verify_id_token(id_token: str) -> Optional[dict]:
    """
    Verify a Firebase ID token and return its claims (uid, email, ...), or None if it is not valid.
    """
    if not id_token or not id_token.strip():
        return None

    if _unverified_allowed():
        print("WARNING: accepting an UNVERIFIED ID token (ALLOW_UNVERIFIED_TOKENS=1, development only)")
        return _decode_without_verification(id_token)

    try:
        return _verify(id_token.strip())
    except Exception as e:
        print(f"WARNING: ID token rejected: {type(e).__name__}")
        return None

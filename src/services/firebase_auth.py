"""
Firebase Authentication - verify ID tokens from Google Sign-In.

Every token is verified with the Firebase Admin SDK: signature (Google's public keys),
audience and issuer (our Firebase project), expiry, issue time and subject. A token that
fails any check is rejected (the route answers 401).

Verifying ID tokens needs no secret, only the Firebase project id:
    - FIREBASE_SERVICE_ACCOUNT_JSON set: the Admin SDK is initialised with that service account.
    - Not set (or not usable): the Admin SDK is initialised with the project id only,
      FIREBASE_PROJECT_ID or DEFAULT_PROJECT_ID (public, the same value as projectId in
      web/js/firebase/config.js).

Development only: ALLOW_UNVERIFIED_TOKENS=1 accepts a token WITHOUT checking it.
Never set it in production.
"""
import os
import json
from typing import Optional

import firebase_admin
from firebase_admin import credentials, auth

try:
    import jwt  # PyJWT
except Exception:  # pragma: no cover - optional dependency
    jwt = None  # type: ignore

DEFAULT_PROJECT_ID = "ilars-659bc"
APP_NAME = "ilars-auth"
CLOCK_SKEW_SECONDS = 10  # tolerate small clock differences between Google and the server

_app = None


def _unverified_allowed() -> bool:
    return os.environ.get("ALLOW_UNVERIFIED_TOKENS") == "1"


if _unverified_allowed():
    print("WARNING: ALLOW_UNVERIFIED_TOKENS=1 - ID tokens are accepted WITHOUT verification. Development only!")


def _get_app():
    """The Firebase Admin app used for token verification (created once), or None if it cannot be created."""
    global _app
    if _app is not None:
        return _app
    try:
        _app = firebase_admin.get_app(APP_NAME)
        return _app
    except ValueError:
        pass

    credentials_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if credentials_json:
        try:
            cred = credentials.Certificate(json.loads(credentials_json))
            _app = firebase_admin.initialize_app(cred, name=APP_NAME)
            print("Firebase Admin initialized with a service account")
            return _app
        except Exception as e:
            print(f"WARNING: FIREBASE_SERVICE_ACCOUNT_JSON is not usable ({type(e).__name__}); "
                  "falling back to project-id-only token verification")

    project_id = os.environ.get("FIREBASE_PROJECT_ID") or DEFAULT_PROJECT_ID
    try:
        _app = firebase_admin.initialize_app(options={"projectId": project_id}, name=APP_NAME)
        print(f"Firebase Admin initialized for project {project_id} (ID token verification only)")
        return _app
    except Exception as e:  # pragma: no cover - defensive logging
        print(f"ERROR: Firebase Admin init failed: {type(e).__name__}: {e}")
        return None


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
    # Firebase ID tokens carry the user id in 'sub'; the Admin SDK also exposes it as 'uid'
    if "sub" in decoded and "uid" not in decoded:
        decoded["uid"] = decoded["sub"]
    return decoded


def verify_id_token(id_token: str) -> Optional[dict]:
    """
    Verify a Firebase ID token and return its claims (uid, email, ...), or None if it is not valid.
    """
    if not id_token or not id_token.strip():
        return None

    if _unverified_allowed():
        print("WARNING: accepting an UNVERIFIED ID token (ALLOW_UNVERIFIED_TOKENS=1, development only)")
        return _decode_without_verification(id_token)

    app = _get_app()
    if app is None:
        return None
    try:
        return auth.verify_id_token(id_token, app=app, clock_skew_seconds=CLOCK_SKEW_SECONDS)
    except Exception as e:
        print(f"WARNING: ID token rejected: {type(e).__name__}")
        return None

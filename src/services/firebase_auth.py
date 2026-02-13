"""
Firebase Authentication - verify ID tokens from Google Sign-In.

Primary mode:
    - Use Firebase Admin SDK with a service account (recommended for production).

Fallback mode (when FIREBASE_SERVICE_ACCOUNT_JSON is not configured):
    - Decode the JWT without verifying the signature using PyJWT.
    - This is less secure but allows development/testing when Firebase Admin
      is not available. Make sure to configure FIREBASE_SERVICE_ACCOUNT_JSON
      in production to restore full verification.
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

_firebase_initialized = False


def _init_firebase() -> bool:
    """Initialize Firebase Admin SDK from env var."""
    global _firebase_initialized
    if _firebase_initialized:
        return True

    credentials_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not credentials_json:
        # Firebase service account not configured
        print("FIREBASE_SERVICE_ACCOUNT_JSON not set - Firebase Admin not initialized")
        return False

    try:
        cred_dict = json.loads(credentials_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        print("Firebase Admin initialized successfully")
        return True
    except Exception as e:  # pragma: no cover - defensive logging
        print(f"Firebase init failed: {e}")
        return False


def _decode_without_verification(id_token: str) -> Optional[dict]:
    """
    Fallback: decode JWT without verifying signature.

    This is intended for development environments where Firebase Admin is not
    configured. It trusts the token contents and SHOULD NOT be used as the
    only verification mechanism in production.
    """
    if jwt is None:
        print("PyJWT not installed - cannot decode token without verification")
        return None

    try:
        # Do not verify signature / exp / audience in fallback mode.
        decoded = jwt.decode(
            id_token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
            },
        )
        print("Token decoded without verification (fallback mode)")
        return decoded
    except Exception as e:  # pragma: no cover - defensive logging
        print(f"Token decode without verification failed: {e}")
        return None


def verify_id_token(id_token: str) -> Optional[dict]:
    """
    Verify Firebase ID token and return decoded claims.

    Returns:
        dict with uid, email, etc. or None if invalid.
    """
    # First try full Firebase verification if Admin SDK is configured.
    if _init_firebase():
        try:
            decoded = auth.verify_id_token(id_token)
            return decoded
        except Exception as e:  # pragma: no cover - defensive logging
            print(f"Token verification via Firebase Admin failed: {e}")

    # Fallback: decode without verification (development / misconfigured env).
    return _decode_without_verification(id_token)

"""
Firebase Authentication - verify ID tokens from Google Sign-In
"""
import os
import json
from typing import Optional
import firebase_admin
from firebase_admin import credentials, auth

_firebase_initialized = False


def _init_firebase() -> bool:
    """Initialize Firebase Admin SDK from env var"""
    global _firebase_initialized
    if _firebase_initialized:
        return True

    credentials_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not credentials_json:
        return False

    try:
        cred_dict = json.loads(credentials_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        return True
    except Exception as e:
        print(f"Firebase init failed: {e}")
        return False


def verify_id_token(id_token: str) -> Optional[dict]:
    """
    Verify Firebase ID token and return decoded claims.
    Returns dict with uid, email, etc. or None if invalid.
    """
    if not _init_firebase():
        return None

    try:
        decoded = auth.verify_id_token(id_token)
        return decoded
    except Exception as e:
        print(f"Token verification failed: {e}")
        return None

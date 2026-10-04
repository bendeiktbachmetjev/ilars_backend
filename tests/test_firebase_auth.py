"""
Tests for ID token verification (src/services/firebase_auth.py).

Google's public keys are replaced by a test key pair, so a token signed with the test key
plays the role of a real Firebase ID token. No network or secret is needed.

The tests must pass WITHOUT Google application credentials, like the production server
(run with HOME pointing to an empty folder to be sure).

Run from the backend folder (needs firebase-admin's dependencies google-auth, cachecontrol, cryptography):
    python3 -m unittest discover -s tests -v
"""
import base64
import datetime
import json
import os
import time
import unittest
from unittest import mock

try:
    import google.oauth2.id_token as google_id_token
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.x509.oid import NameOID
    HAVE_DEPS = True
except ImportError:  # pragma: no cover
    HAVE_DEPS = False

PROJECT = "ilars-659bc"
KID = "test-key-1"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _make_key_and_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return key, cert.public_bytes(serialization.Encoding.PEM).decode()


def _sign(key, claims: dict, header: dict = None) -> str:
    head = header or {"alg": "RS256", "kid": KID, "typ": "JWT"}
    signing_input = _b64(json.dumps(head).encode()) + "." + _b64(json.dumps(claims).encode())
    sig = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return signing_input + "." + _b64(sig)


def _claims(**over):
    now = int(time.time())
    c = {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT, "auth_time": now - 60,
         "iat": now - 60, "exp": now + 3600, "sub": "doctorUid123", "email": "doctor@example.org"}
    c.update(over)
    return c


@unittest.skipUnless(HAVE_DEPS, "google-auth / cryptography not installed")
class VerifyIdTokenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key, cls.cert = _make_key_and_cert()
        cls.other_key, _ = _make_key_and_cert()

    def setUp(self):
        from src.services import firebase_auth
        self.fa = firebase_auth
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ("FIREBASE_SERVICE_ACCOUNT_JSON", "FIREBASE_PROJECT_ID", "ALLOW_UNVERIFIED_TOKENS",
                  "FIREBASE_AUTH_EMULATOR_HOST"):
            os.environ.pop(k, None)
        # Google's public keys -> the test certificate
        self.certs = mock.patch.object(google_id_token, "_fetch_certs", return_value={KID: self.cert})
        self.certs.start()

    def tearDown(self):
        self.certs.stop()
        self.env.stop()

    def test_valid_token_without_service_account(self):
        decoded = self.fa.verify_id_token(_sign(self.key, _claims()))
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["uid"], "doctorUid123")
        self.assertEqual(decoded["email"], "doctor@example.org")

    def test_unsigned_token_rejected(self):
        unsigned = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode()) + "." + \
            _b64(json.dumps(_claims()).encode()) + "."
        self.assertIsNone(self.fa.verify_id_token(unsigned))

    def test_token_signed_by_another_key_rejected(self):
        self.assertIsNone(self.fa.verify_id_token(_sign(self.other_key, _claims())))

    def test_token_of_another_project_rejected(self):
        other = _claims(aud="someone-else", iss="https://securetoken.google.com/someone-else")
        self.assertIsNone(self.fa.verify_id_token(_sign(self.key, other)))

    def test_expired_token_rejected(self):
        now = int(time.time())
        self.assertIsNone(self.fa.verify_id_token(_sign(self.key, _claims(iat=now - 7200, exp=now - 3600))))

    def test_empty_or_garbage_rejected(self):
        self.assertIsNone(self.fa.verify_id_token(""))
        self.assertIsNone(self.fa.verify_id_token("not-a-jwt"))

    def test_service_account_variable_not_needed_or_used(self):
        os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"] = "{not json"
        self.assertIsNotNone(self.fa.verify_id_token(_sign(self.key, _claims())))
        self.assertIsNone(self.fa.verify_id_token(_sign(self.other_key, _claims())))

    def test_token_without_kid_or_wrong_alg_rejected(self):
        self.assertIsNone(self.fa.verify_id_token(_sign(self.key, _claims(), {"alg": "RS256", "typ": "JWT"})))

    def test_wrong_issuer_or_empty_subject_rejected(self):
        self.assertIsNone(self.fa.verify_id_token(_sign(self.key, _claims(iss="https://accounts.google.com"))))
        self.assertIsNone(self.fa.verify_id_token(_sign(self.key, _claims(sub=""))))

    def test_project_id_from_env(self):
        os.environ["FIREBASE_PROJECT_ID"] = "another-project"
        self.assertIsNone(self.fa.verify_id_token(_sign(self.key, _claims())))
        other = _claims(aud="another-project", iss="https://securetoken.google.com/another-project")
        self.assertIsNotNone(self.fa.verify_id_token(_sign(self.key, other)))

    def test_development_flag_accepts_unverified(self):
        os.environ["ALLOW_UNVERIFIED_TOKENS"] = "1"
        decoded = self.fa.verify_id_token(_sign(self.other_key, _claims(sub="devUid")))
        self.assertEqual(decoded["uid"], "devUid")


if __name__ == "__main__":
    unittest.main()

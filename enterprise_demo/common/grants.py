from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_grant(claims: dict[str, Any], private_key_path: Path) -> str:
    header = {"alg": "RS256", "typ": "BAP-GRANT", "kid": "demo-bap-signing-1"}
    encoded_header = _encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    encoded_claims = _encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{encoded_header}.{encoded_claims}.{_encode(signature)}"


def verify_grant(token: str, public_key_path: Path) -> tuple[bool, dict[str, Any] | str]:
    try:
        encoded_header, encoded_claims, encoded_signature = token.split(".")
        signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
        public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
        public_key.verify(_decode(encoded_signature), signing_input, padding.PKCS1v15(), hashes.SHA256())
        claims = json.loads(_decode(encoded_claims))
        if int(claims.get("exp", 0)) <= int(time.time()):
            return False, "Grant expired"
        return True, claims
    except (ValueError, KeyError, json.JSONDecodeError, InvalidSignature) as error:
        return False, f"Invalid grant: {error}"

from __future__ import annotations

import ipaddress
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: E402
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID  # noqa: E402

from common.paths import PKI_ROOT, PFX_PASSWORD, ensure_runtime  # noqa: E402


def name(common_name: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Company BAP Demo"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def issue(
    common_name: str,
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    usage: x509.ObjectIdentifier,
    *,
    server_names: bool = False,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name(common_name))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
    )
    if server_names:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
    return key, builder.sign(ca_key, hashes.SHA256())


def main() -> int:
    ensure_runtime()
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(name("Company BAP Demo Root CA"))
        .issuer_name(name("Company BAP Demo Root CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                key_cert_sign=True,
                key_agreement=False,
                content_commitment=False,
                data_encipherment=False,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    write_key(PKI_ROOT / "demo-ca.key.pem", ca_key)
    write_cert(PKI_ROOT / "demo-ca.cert.pem", ca_cert)

    for prefix, common_name in (
        ("bap-front-door", "bap-front-door.local"),
        ("resource-gateway", "resource-gateway.local"),
    ):
        key, cert = issue(
            common_name,
            ca_key,
            ca_cert,
            ExtendedKeyUsageOID.SERVER_AUTH,
            server_names=True,
        )
        write_key(PKI_ROOT / f"{prefix}.key.pem", key)
        write_cert(PKI_ROOT / f"{prefix}.cert.pem", cert)

    connector_key, connector_cert = issue(
        "laptop-bap-connector",
        ca_key,
        ca_cert,
        ExtendedKeyUsageOID.CLIENT_AUTH,
    )
    write_key(PKI_ROOT / "connector-client.key.pem", connector_key)
    write_cert(PKI_ROOT / "connector-client.cert.pem", connector_cert)
    (PKI_ROOT / "connector-client.pfx").write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"laptop-bap-connector",
            connector_key,
            connector_cert,
            [ca_cert],
            serialization.BestAvailableEncryption(PFX_PASSWORD.encode()),
        )
    )

    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    write_key(PKI_ROOT / "bap-grant-signing.key.pem", signing_key)
    (PKI_ROOT / "bap-grant-signing.public.pem").write_bytes(
        signing_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    code_key, code_cert = issue(
        "Company BAP Demo Code Signing",
        ca_key,
        ca_cert,
        ExtendedKeyUsageOID.CODE_SIGNING,
    )
    (PKI_ROOT / "demo-code-signing.pfx").write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"company-bap-demo-code-signing",
            code_key,
            code_cert,
            [ca_cert],
            serialization.BestAvailableEncryption(PFX_PASSWORD.encode()),
        )
    )
    write_cert(PKI_ROOT / "demo-code-signing.cert.pem", code_cert)
    (PKI_ROOT / "DEMO_ONLY_PASSWORD.txt").write_text(PFX_PASSWORD, encoding="utf-8")
    print(f"Generated demo-only PKI under {PKI_ROOT}")
    print("These certificates and private keys are not suitable for production.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

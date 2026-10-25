"""Per-user localhost identity and Windows trust for the loopback API."""

import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import logging
import os
import shutil
from pathlib import Path
import ssl
import uuid

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

logger = logging.getLogger("ScanLink")
RENEW_BEFORE = timedelta(days=30)
SERVER_AUTH = ExtendedKeyUsageOID.SERVER_AUTH.dotted_string


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _windows_crypto():
    if os.name != "nt":
        raise OSError("Automatic certificate setup requires Windows")
    return ctypes.WinDLL("crypt32", use_last_error=True)


def _protect_secret(value, decrypt=False):
    crypto = _windows_crypto()
    buffer = ctypes.create_string_buffer(value)
    source = DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = DataBlob()
    # CRYPTPROTECT_UI_FORBIDDEN: the secret is bound to this Windows user's login.
    arguments = [
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypto.CryptUnprotectData.argtypes = arguments
    crypto.CryptUnprotectData.restype = wintypes.BOOL
    crypto.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        *arguments[2:],
    ]
    crypto.CryptProtectData.restype = wintypes.BOOL
    if decrypt:
        ok = crypto.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)
        )
    else:
        ok = crypto.CryptProtectData(
            ctypes.byref(source),
            "ScanLink HTTPS",
            None,
            None,
            None,
            1,
            ctypes.byref(target),
        )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def _is_trusted(der):
    if os.name != "nt":
        return False
    return any(
        encoded == der
        and encoding == "x509_asn"
        and (trust is True or SERVER_AUTH in trust)
        for encoded, encoding, trust in ssl.enum_certificates("ROOT")
    )


def _install_trust(der):
    crypto = _windows_crypto()
    crypto.CertOpenStore.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    crypto.CertOpenStore.restype = ctypes.c_void_p
    crypto.CertAddEncodedCertificateToStore.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    crypto.CertAddEncodedCertificateToStore.restype = wintypes.BOOL
    crypto.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    crypto.CertCloseStore.restype = wintypes.BOOL
    # SYSTEM_W provider, CURRENT_USER, OPEN_EXISTING. Never change machine trust.
    store = crypto.CertOpenStore(
        10, 0, None, 0x00010000 | 0x00004000, ctypes.c_wchar_p("ROOT")
    )
    if not store:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        logger.info("Requesting Windows current-user trust for ScanLink localhost")
        encoded = ctypes.create_string_buffer(der)
        # ADD_NEW: do not replace or remove another certificate.
        if not crypto.CertAddEncodedCertificateToStore(
            store, 1, encoded, len(der), 1, None
        ):
            if not _is_trusted(der):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        crypto.CertCloseStore(store, 0)
    if not _is_trusted(der):
        raise OSError("Windows did not trust the ScanLink certificate")
    logger.info("Windows current-user certificate trust verified")


class LocalIdentity:
    def __init__(self, app_dir):
        self.root = Path(app_dir) / "https"
        self.pointer = self.root / "active.json"

    def _read(self):
        identity = json.loads(self.pointer.read_text(encoding="utf-8"))["identity"]
        if (
            not isinstance(identity, str)
            or len(identity) != 32
            or any(c not in "0123456789abcdef" for c in identity)
        ):
            raise ValueError("Invalid ScanLink certificate identity")
        directory = self.root / identity
        certificate = x509.load_pem_x509_certificate(
            (directory / "localhost.pem").read_bytes()
        )
        certificate.verify_directly_issued_by(certificate)
        if certificate.subject != x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "ScanLink localhost")]
        ):
            raise ValueError("Unexpected ScanLink certificate subject")
        if certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value.ca:
            raise ValueError("ScanLink must not install a certificate authority")
        names = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        if set(names.get_values_for_type(x509.DNSName)) != {"localhost"} or set(
            names.get_values_for_type(x509.IPAddress)
        ) != {ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1")}:
            raise ValueError("Unexpected ScanLink certificate names")
        if set(
            certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        ) != {ExtendedKeyUsageOID.SERVER_AUTH}:
            raise ValueError("Unexpected ScanLink certificate purpose")
        password = _protect_secret(
            (directory / "password.dpapi").read_bytes(), decrypt=True
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(directory / "localhost.pem"), password=password)
        return certificate, context

    def context(self):
        certificate, context = self._read()
        now = datetime.now(timezone.utc)
        if (
            not certificate.not_valid_before_utc
            <= now
            < certificate.not_valid_after_utc
        ):
            raise ValueError("ScanLink certificate is not currently valid")
        if not _is_trusted(certificate.public_bytes(serialization.Encoding.DER)):
            raise OSError("ScanLink certificate is not trusted")
        return context

    def ensure(self):
        try:
            certificate, context = self._read()
            now = datetime.now(timezone.utc)
            if (
                certificate.not_valid_before_utc <= now
                and certificate.not_valid_after_utc > now + RENEW_BEFORE
            ):
                needs_renewal = False
            else:
                needs_renewal = True
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            InvalidSignature,
            x509.ExtensionNotFound,
        ):
            needs_renewal = True
        if needs_renewal:
            logger.info("Preparing a new ScanLink localhost identity")
            return self._create()
        der = certificate.public_bytes(serialization.Encoding.DER)
        if not _is_trusted(der):
            _install_trust(der)
        return context

    def _create(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "ScanLink localhost")]
        )
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=None,
                    decipher_only=None,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                        x509.IPAddress(ipaddress.ip_address("::1")),
                    ]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        logger.info("Localhost server certificate generated")
        identity = uuid.uuid4().hex
        directory = self.root / identity
        directory.mkdir(parents=True, mode=0o700)
        password = base64.b64encode(os.urandom(32))
        secret = _protect_secret(password)
        logger.info("Localhost private-key password protected with Windows DPAPI")
        bundle = certificate.public_bytes(
            serialization.Encoding.PEM
        ) + key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password),
        )
        (directory / "localhost.pem").write_bytes(bundle)
        (directory / "password.dpapi").write_bytes(secret)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(directory / "localhost.pem"), password=password)
        # Immutable identity directories retain previous and interrupted attempts.
        pending = directory / "active.json"
        pending.write_text(json.dumps({"identity": identity}), encoding="utf-8")
        if self.pointer.exists():
            previous = directory / "previous-active.json"
            previous.write_bytes(self.pointer.read_bytes())
        os.replace(pending, self.pointer)
        _install_trust(certificate.public_bytes(serialization.Encoding.DER))
        if (directory / "previous-active.json").exists():
            try:
                old_identity = json.loads(
                    (directory / "previous-active.json").read_text()
                )["identity"]
                if (
                    isinstance(old_identity, str)
                    and len(old_identity) == 32
                    and all(c in "0123456789abcdef" for c in old_identity)
                ):
                    old_directory = self.root / old_identity
                    archive = self.root.parent / ".xclude" / "https" / old_identity
                    if old_directory.is_dir() and old_directory != directory:
                        archive.parent.mkdir(parents=True, exist_ok=True)
                        suffix = 1
                        original_archive = archive
                        while archive.exists():
                            archive = original_archive.with_name(
                                f"{original_archive.name}-{suffix}"
                            )
                            suffix += 1
                        shutil.move(str(old_directory), str(archive))
            except (OSError, ValueError, KeyError):
                logger.warning(
                    "Could not archive previous HTTPS identity", exc_info=True
                )
        logger.info(
            "ScanLink localhost certificate ready; expires %s",
            certificate.not_valid_after_utc.isoformat(),
        )
        return context

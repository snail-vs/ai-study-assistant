import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EncryptionError(ValueError):
    pass


def _master_key() -> bytes:
    value = os.getenv("STUDYCENTER_ENCRYPTION_KEY", "").strip()
    if not value:
        raise EncryptionError("STUDYCENTER_ENCRYPTION_KEY is not configured")
    try:
        key = base64.urlsafe_b64decode(value.encode())
    except Exception as exc:
        raise EncryptionError("STUDYCENTER_ENCRYPTION_KEY must be urlsafe base64") from exc
    if len(key) not in (16, 24, 32):
        raise EncryptionError("STUDYCENTER_ENCRYPTION_KEY must decode to 16, 24, or 32 bytes")
    return key


def encrypt_secret(value: str) -> tuple[str, str]:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_master_key()).encrypt(nonce, value.encode(), None)
    return (
        base64.urlsafe_b64encode(ciphertext).decode(),
        base64.urlsafe_b64encode(nonce).decode(),
    )


def decrypt_secret(ciphertext: str, nonce: str) -> str:
    try:
        plain = AESGCM(_master_key()).decrypt(
            base64.urlsafe_b64decode(nonce), base64.urlsafe_b64decode(ciphertext), None
        )
        return plain.decode()
    except EncryptionError:
        raise
    except Exception as exc:
        raise EncryptionError("Provider credential could not be decrypted") from exc

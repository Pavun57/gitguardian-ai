"""BYOK key encryption.

Fernet (AES-128-CBC + HMAC-SHA256) with a single master key from env. Ciphertexts are
versioned ("v1:<token>") so a future migration to envelope encryption (KMS/Vault) or
MultiFernet rotation touches only this file — callers see only encrypt_key/decrypt_key.

Never log decrypted values; core/logging.py's scrubber is the second line of defense.
"""

from cryptography.fernet import Fernet, InvalidToken

from core.config import get_settings

_VERSION_PREFIX = "v1:"


class EncryptionError(Exception):
    pass


def _fernet() -> Fernet:
    key = get_settings().master_encryption_key
    if not key:
        raise EncryptionError(
            "MASTER_ENCRYPTION_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_key(plaintext: str) -> bytes:
    """Encrypt a user's API key for at-rest storage. Returns versioned ciphertext."""
    if not plaintext:
        raise EncryptionError("Refusing to encrypt an empty key")
    token = _fernet().encrypt(plaintext.encode()).decode()
    return (_VERSION_PREFIX + token).encode()


def decrypt_key(ciphertext: bytes) -> str:
    """Decrypt a stored API key. Raises EncryptionError on tamper/wrong master key."""
    raw = ciphertext.decode() if isinstance(ciphertext, (bytes, bytearray)) else ciphertext
    if raw.startswith(_VERSION_PREFIX):
        raw = raw[len(_VERSION_PREFIX) :]
    try:
        return _fernet().decrypt(raw.encode()).decode()
    except InvalidToken as e:
        raise EncryptionError("Failed to decrypt key (wrong master key or corrupted data)") from e


def fingerprint(plaintext: str) -> str:
    """Non-reversible display hint, e.g. 'sk-ant-...wxyz'."""
    return f"...{plaintext[-4:]}" if len(plaintext) >= 8 else "..."

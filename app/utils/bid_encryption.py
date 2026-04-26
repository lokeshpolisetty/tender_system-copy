"""
Bid amount encryption / decryption using Fernet (AES-128-CBC + HMAC-SHA256).

On first use a key is auto-generated and stored in the SECRET_KEY-derived
bytes so it is consistent across restarts without a separate env var.
Production deployments should supply BID_ENCRYPTION_KEY explicitly.
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _get_fernet() -> Fernet:
    """Return a Fernet instance keyed to the application secret."""
    key_env = current_app.config.get('BID_ENCRYPTION_KEY')
    if key_env:
        key = key_env.encode() if isinstance(key_env, str) else key_env
        # Ensure it is a valid 32-byte URL-safe base64 key
        try:
            return Fernet(key)
        except Exception:
            pass  # Fall through to derived key

    # Derive a 32-byte key from SECRET_KEY via SHA-256
    secret = current_app.config['SECRET_KEY'].encode()
    derived = hashlib.sha256(secret).digest()
    fernet_key = base64.urlsafe_b64encode(derived)
    return Fernet(fernet_key)


def encrypt_bid_amount(amount: float) -> str:
    """
    Encrypt a bid amount.

    Returns a URL-safe base64 string that can be stored in the database.
    The actual amount is NOT readable until explicitly decrypted.
    """
    f = _get_fernet()
    plaintext = str(amount).encode()
    return f.encrypt(plaintext).decode()


def decrypt_bid_amount(token: str) -> float:
    """
    Decrypt an encrypted bid amount token.

    Returns the float amount, or raises ValueError on tampered/invalid data.
    """
    f = _get_fernet()
    try:
        plaintext = f.decrypt(token.encode())
        return float(plaintext.decode())
    except (InvalidToken, ValueError) as e:
        raise ValueError(f'Bid decryption failed — data may be tampered: {e}')

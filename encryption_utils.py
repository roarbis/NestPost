from cryptography.fernet import Fernet
import os
from pathlib import Path

KEY_FILE = str(Path(__file__).parent.resolve() / ".secret.key")


def get_or_create_key() -> bytes:
    # Prefer env var (required for Render / cloud deployments)
    env_key = os.environ.get("FERNET_KEY", "")
    if env_key:
        return env_key.encode()

    # Fall back to local file (dev mode)
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    return key


def encrypt_value(value: str) -> str:
    if not value:
        return value
    f = Fernet(get_or_create_key())
    return f.encrypt(value.encode()).decode()


def decrypt_value(encrypted_value: str) -> str:
    if not encrypted_value:
        return encrypted_value
    try:
        f = Fernet(get_or_create_key())
        return f.decrypt(encrypted_value.encode()).decode()
    except Exception:
        return ""

"""Clés API stockées dans le Gestionnaire d'identification Windows (keyring)."""
import keyring
from keyring.errors import KeyringError

SERVICE = "HubWindows"
ANTHROPIC = "anthropic_admin_key"
OPENAI = "openai_admin_key"


def get(name: str) -> str:
    try:
        return keyring.get_password(SERVICE, name) or ""
    except KeyringError:
        return ""


def set(name: str, value: str) -> None:  # noqa: A001
    value = value.strip()
    if value:
        keyring.set_password(SERVICE, name, value)
    else:
        try:
            keyring.delete_password(SERVICE, name)
        except KeyringError:
            pass

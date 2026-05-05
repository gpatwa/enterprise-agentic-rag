# services/api/app/mcp/crypto.py
"""
Symmetric encryption for stored MCP credentials.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library,
which is already a transitive dependency via python-jose[cryptography].

Threat model
------------
Protects against: a DB dump leaking SaaS tokens.
Does NOT protect against: an attacker with code-exec on the API pod —
they can read MCP_ENCRYPTION_KEY from settings and decrypt at will.
That tier of attack is the secrets-vault layer's problem.

Key management
--------------
The master key is a 32-byte URL-safe-base64 Fernet key. It's read from
the SecretsClient at boot under name `MCP_ENCRYPTION_KEY`. We don't
support rotation in Phase 1 — when we add it, the column will gain a
`key_version` integer and the manager will try multiple keys on decrypt.

Format note: stored ciphertext is text (Fernet's URL-safe-base64 output),
which keeps the column human-inspectable in the DB and avoids bytea
encoding pain across asyncpg versions.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

from app.mcp.errors import MCPCryptoError

logger = logging.getLogger(__name__)


class CredentialCipher:
    """
    Stateless wrapper over a single Fernet key.

    Instantiate once per process from the resolved master key (typically
    in lifespan). Treat as a singleton via `get_cipher()` below.
    """

    def __init__(self, master_key: str) -> None:
        if not master_key:
            raise MCPCryptoError("master key is empty")
        try:
            self._fernet = Fernet(master_key.encode("ascii"))
        except (ValueError, TypeError) as e:
            # Hide the bad key from the message; only its length is safe to log.
            raise MCPCryptoError(
                "MCP_ENCRYPTION_KEY is not a valid Fernet key (32-byte url-safe base64 expected)",
                extra={"key_length": len(master_key)},
            ) from e

    def encrypt(self, payload: dict[str, Any]) -> str:
        """JSON-encode and encrypt. Returns Fernet's URL-safe base64 token."""
        try:
            blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            return self._fernet.encrypt(blob).decode("ascii")
        except Exception as e:
            # Don't echo the payload — even a fragment can leak secrets.
            raise MCPCryptoError("encrypt failed") from e

    def decrypt(self, token: str) -> dict[str, Any]:
        """Decrypt and JSON-decode. Raises MCPCryptoError on any failure."""
        try:
            blob = self._fernet.decrypt(token.encode("ascii"))
            return json.loads(blob.decode("utf-8"))
        except InvalidToken as e:
            # Wrong key, tampered ciphertext, or expired (we don't use TTLs
            # but keeping the catch is defensive).
            raise MCPCryptoError("decrypt failed: invalid token") from e
        except Exception as e:
            raise MCPCryptoError("decrypt failed") from e


# ── Process-wide singleton, set during lifespan ──────────────────────────
_cipher: Optional[CredentialCipher] = None


def init_cipher(master_key: str) -> None:
    """Set the process cipher. Called once by lifespan after secrets are pulled."""
    global _cipher
    if _cipher is not None:
        # Re-init in tests is fine; in prod it indicates a logic bug we want to know.
        logger.warning("MCP cipher re-initialised (tests OK; flag in prod)")
    _cipher = CredentialCipher(master_key)


def get_cipher() -> CredentialCipher:
    """Fetch the singleton. Raises MCPCryptoError if init_cipher() wasn't called."""
    if _cipher is None:
        raise MCPCryptoError(
            "MCP cipher not initialised — set MCP_ENCRYPTION_KEY and enable MCP_ENABLED"
        )
    return _cipher


def reset_cipher() -> None:
    """Test-only: drop the singleton so each test starts clean."""
    global _cipher
    _cipher = None


def generate_key() -> str:
    """
    Helper for ops + tests. Equivalent to running

        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    Don't call this in app code — keys come from the secrets vault.
    """
    return Fernet.generate_key().decode("ascii")

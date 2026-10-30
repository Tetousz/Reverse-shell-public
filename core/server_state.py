"""Persistent server state — master secret + payload registry + meta.

Stored under ~/.config/reverse-shell/servers/<instance>/ by default.
Survives dashboard restarts, so previously-exported payloads keep working.

Layout per instance:
    secret         master HMAC secret (plaintext, chmod 0600)
    registry.json  {"payloads": {uuid: {created_at, last_auth, ...}}}
    meta.json      instance metadata (created_at, instance name)
"""

import json
import os
import secrets
import time
from pathlib import Path


DEFAULT_HOME = Path.home() / ".config" / "reverse-shell"
DEFAULT_INSTANCE = "default"
DEFAULT_PRUNE_DAYS = 30


class ServerState:
    """Persistence layer for a single server instance.

    Construct once per instance; pass the same object to Server / ExportManager
    so they see the same secret and registry.
    """

    def __init__(
        self,
        home=None,
        instance=None,
        migration_secret=None,
    ):
        self.home = Path(home) if home else DEFAULT_HOME
        self.instance = instance or DEFAULT_INSTANCE
        self.instance_dir = self.home / "servers" / self.instance
        self.instance_dir.mkdir(parents=True, exist_ok=True)

        self.secret_path = self.instance_dir / "secret"
        self.registry_path = self.instance_dir / "registry.json"
        self.meta_path = self.instance_dir / "meta.json"

        self._migration_secret = migration_secret
        self._secret = self._load_or_create_secret()
        self._registry = self._load_or_create_registry()
        self._meta = self._load_or_create_meta()

    # ---- identity --------------------------------------------------------

    @property
    def server_uuid(self):
        return self.instance

    def get_secret(self):
        return self._secret

    def get_meta(self):
        return self._meta

    # ---- secret ----------------------------------------------------------

    def _load_or_create_secret(self):
        if self.secret_path.is_file():
            return self.secret_path.read_text().strip()

        # First run: migrate from caller-supplied secret if given,
        # otherwise generate a fresh one.
        if self._migration_secret:
            secret = self._migration_secret
        else:
            secret = secrets.token_hex(32)

        self.secret_path.write_text(secret)
        try:
            os.chmod(self.secret_path, 0o600)
        except OSError:
            pass
        return secret

    # ---- registry --------------------------------------------------------

    def _load_or_create_registry(self):
        if self.registry_path.is_file():
            try:
                data = json.loads(self.registry_path.read_text())
                if isinstance(data, dict) and "payloads" in data:
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        registry = {"payloads": {}}
        self._write_registry(registry)
        return registry

    def _write_registry(self, registry):
        self.registry_path.write_text(json.dumps(registry, indent=2))

    def get_registry(self):
        return self._registry

    def has_payload(self, payload_uuid):
        return payload_uuid in self._registry.get("payloads", {})

    def register_payload(self, payload_uuid, metadata=None):
        """Add a payload to the registry. Returns True if newly added."""
        payloads = self._registry.setdefault("payloads", {})
        if payload_uuid in payloads:
            return False
        payloads[payload_uuid] = {
            "created_at": time.time(),
            "last_auth": None,
            **(metadata or {}),
        }
        self._write_registry(self._registry)
        return True

    def touch_payload(self, payload_uuid):
        """Record that a payload just authenticated."""
        payloads = self._registry.get("payloads", {})
        if payload_uuid in payloads:
            payloads[payload_uuid]["last_auth"] = time.time()
            self._write_registry(self._registry)
            return True
        return False

    def get_registry_stats(self):
        """Return {total, stale} counts for the current registry.

        Non-destructive — read-only. Use prune_stale() to actually remove
        entries older than DEFAULT_PRUNE_DAYS.
        """
        payloads = self._registry.get("payloads", {})
        total = len(payloads)
        if total == 0:
            return {"total": 0, "stale": 0}
        cutoff = time.time() - DEFAULT_PRUNE_DAYS * 86400
        stale = sum(
            1 for info in payloads.values()
            if (info.get("last_auth") or info.get("created_at") or 0) < cutoff
        )
        return {"total": total, "stale": stale}

    def revoke_payload(self, payload_uuid):
        """Remove a payload from the registry.

        After revocation, any auth attempt using this payload_uuid will
        be rejected with 'unregistered payload'. Returns True if the
        payload was present.
        """
        payloads = self._registry.get("payloads", {})
        if payload_uuid not in payloads:
            return False
        del payloads[payload_uuid]
        self._write_registry(self._registry)
        return True

    def prune_stale(self, days=DEFAULT_PRUNE_DAYS):
        """Remove payloads unused for `days`. Returns list of removed UUIDs."""
        payloads = self._registry.get("payloads", {})
        cutoff = time.time() - days * 86400
        stale = [
            uuid
            for uuid, info in payloads.items()
            if (info.get("last_auth") or info.get("created_at") or 0) < cutoff
        ]
        for uuid in stale:
            del payloads[uuid]
        if stale:
            self._write_registry(self._registry)
        return stale

    # ---- meta ------------------------------------------------------------

    def _load_or_create_meta(self):
        if self.meta_path.is_file():
            try:
                return json.loads(self.meta_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        meta = {
            "created_at": time.time(),
            "instance": self.instance,
        }
        self.meta_path.write_text(json.dumps(meta, indent=2))
        return meta

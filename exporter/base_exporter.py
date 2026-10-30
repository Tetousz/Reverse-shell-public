"""Abstract base for all payload exporters.

Each concrete exporter turns the client source into a *launcher* file
for one target format (py, sh, bat, js, exe). The Base64 blob is always
produced via :meth:`BaseExporter.payload_literal` so no format
re-invents the encoding path.
"""

from abc import ABC, abstractmethod

from exporter import obfuscator


class BaseExporter(ABC):
    """Contract every format exporter must satisfy."""

    #: Short format key used by ExportManager (e.g. "py", "sh").
    format_name: str = ""

    #: File extension including leading dot (e.g. ".py").
    extension: str = ""

    def __init__(self, chunk_size: int = obfuscator.DEFAULT_CHUNK_SIZE):
        self.chunk_size = chunk_size

    # ---- public contract -------------------------------------------------

    @abstractmethod
    def export(self, client_source: str) -> str:
        """Return the main launcher file content as a string.

        ``client_source`` is the raw Python source of ``client/client.py``.
        """

    def companion_files(self, client_source: str) -> dict:
        """Extra files this exporter needs written alongside the main output.

        Default: none. Formats that emit more than one file (e.g. the
        PyInstaller spec + its launcher .py) override this.

        Returns a mapping ``{filename: content}``.
        """
        return {}

    # ---- shared helpers --------------------------------------------------

    def payload_literal(self, client_source: str, indent: str = "    ") -> str:
        """Base64-encode ``client_source`` and render it as a Python string literal.

        Formats that embed the blob in a *Python* file (py, exe) use this
        directly. Shell/batch formats reuse the underlying encoded string
        via :meth:`payload_encoded` and roll their own wrapping.
        """
        encoded = self.payload_encoded(client_source)
        return obfuscator.chunked_literal(encoded, size=self.chunk_size, indent=indent)

    def payload_encoded(self, client_source: str) -> str:
        """Just the raw Base64 string (no line breaks)."""
        return obfuscator.encode(client_source)

    # ---- dunder ----------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{type(self).__name__} format={self.format_name!r} ext={self.extension!r}>"

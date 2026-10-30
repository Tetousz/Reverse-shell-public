"""Base64 obfuscation helpers for payload exporters.

Pure functions only — no I/O. Every exporter embeds the client source
as a Base64 blob produced here, so this is the single source of truth
for encoding and chunk formatting.
"""

import base64

DEFAULT_CHUNK_SIZE = 76  # PEM-style line width


def encode(source: str) -> str:
    """Base64-encode a UTF-8 string. Returns ASCII str."""
    return base64.b64encode(source.encode("utf-8")).decode("ascii")


def decode(encoded: str) -> str:
    """Inverse of :func:`encode`. Useful for tests and future introspection."""
    return base64.b64decode(encoded.encode("ascii")).decode("utf-8")


def wrap_chunks(encoded: str, size: int = DEFAULT_CHUNK_SIZE) -> list:
    """Split a Base64 string into fixed-width lines.

    Keeps generated launchers readable and avoids a single mega-line
    that some Windows editors / batch parsers choke on.
    """
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [encoded[i:i + size] for i in range(0, len(encoded), size)]


def chunked_literal(encoded: str, size: int = DEFAULT_CHUNK_SIZE,
                    indent: str = "    ") -> str:
    """Render a Base64 string as an indented multi-line Python string literal.

    Returns source like::

        "AAAA\n
         BBBB\n
         CCCC"

    Caller is responsible for assigning it, e.g.::

        _B64 = (
            <this output>
        )
    """
    chunks = wrap_chunks(encoded, size)
    lines = []
    for i, chunk in enumerate(chunks):
        suffix = "\\n" if i < len(chunks) - 1 else ""
        lines.append(f'{indent}"{chunk}{suffix}"')
    return "\n".join(lines)

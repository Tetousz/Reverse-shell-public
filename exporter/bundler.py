"""Bundle an exported payload with the packages it needs at runtime.

The client currently does ``from core...`` imports, so a bare payload
file can't run outside the project tree. Bundling ships the payload
together with a copy of those packages, producing a portable artifact.
"""

import shutil
import zipfile
from pathlib import Path


#: Package directories the payload needs beside it at runtime.
DEFAULT_COPY_PATHS = ("core",)


def bundle_payload(payload_path: Path, output_dir: Path,
                   copy_paths=DEFAULT_COPY_PATHS) -> Path:
    """Copy ``payload_path`` + each of ``copy_paths`` into a staging dir,
    zip it, and return the path to the resulting ``.zip``.

    ``copy_paths`` are resolved relative to the project root (two levels
    above this file: ``exporter/../``).
    """
    payload_path = Path(payload_path).resolve()
    output_dir = Path(output_dir).resolve()
    project_root = Path(__file__).resolve().parent.parent

    if not payload_path.is_file():
        raise FileNotFoundError(f"Payload not found: {payload_path}")

    # Stage in a sibling dir named after the payload stem.
    stem = payload_path.stem  # e.g. "payload_py"
    staging = output_dir / stem
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # Payload goes at the top level.
    shutil.copy2(payload_path, staging / payload_path.name)

    # Copy each required package alongside it.
    for rel in copy_paths:
        src = (project_root / rel).resolve()
        if not src.is_dir():
            raise FileNotFoundError(f"Bundle source missing: {src}")
        dst = staging / rel
        shutil.copytree(src, dst)

    # Zip the whole staging dir.
    zip_path = output_dir / f"{stem}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(staging.rglob("*")):
            if item.is_file():
                zf.write(item, item.relative_to(staging))

    # Cleanup staging (keep only the zip).
    shutil.rmtree(staging)
    return zip_path

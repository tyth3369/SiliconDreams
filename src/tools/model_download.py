"""Atomic downloader for pinned local model artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.model_artifacts import (
    MARKER_FILENAME,
    ModelArtifact,
    ModelManifest,
    verify_artifact,
    write_verification_marker,
)


def _download_artifact(
    manifest: ModelManifest,
    artifact: ModelArtifact,
    *,
    mirror: str,
    timeout: int,
) -> None:
    destination = manifest.cache_dir / artifact.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if verify_artifact(destination, artifact, verify_hash=True):
        print(f"verified {artifact.path} ({artifact.size / 1_000_000:.1f} MB)")
        return

    destination.unlink(missing_ok=True)
    partial = Path(f"{destination}.part")
    if partial.exists() and partial.stat().st_size > artifact.size:
        partial.unlink()

    url = f"{mirror.rstrip('/')}/{manifest.model_id}/resolve/{manifest.revision}/{artifact.path}"
    print(f"download {artifact.path} from pinned revision {manifest.revision[:12]}")
    command = [
        "curl",
        "-fL",
        "--retry",
        "5",
        "--retry-all-errors",
        "--retry-delay",
        "3",
        "-C",
        "-",
        "-o",
        str(partial),
        url,
    ]
    subprocess.run(command, check=True, timeout=timeout)
    if not verify_artifact(partial, artifact, verify_hash=True):
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded artifact failed size/SHA-256 verification: {artifact.path}")
    partial.replace(destination)


def download_model(
    manifest: ModelManifest,
    *,
    mirror: str = "https://hf-mirror.com",
    timeout: int = 1800,
) -> None:
    manifest.cache_dir.mkdir(parents=True, exist_ok=True)
    (manifest.cache_dir / MARKER_FILENAME).unlink(missing_ok=True)
    for artifact in manifest.artifacts:
        _download_artifact(manifest, artifact, mirror=mirror, timeout=timeout)
    marker = write_verification_marker(manifest)
    print(f"ready: {manifest.cache_dir}")
    print(f"marker: {marker}")

import hashlib
import json
from pathlib import Path

import pytest

from src.model_artifacts import (
    MARKER_FILENAME,
    ModelArtifact,
    ModelManifest,
    model_cache_status,
    write_verification_marker,
)
from src.tools import model_download


def _manifest(root: Path, content: bytes = b"verified model") -> ModelManifest:
    return ModelManifest(
        model_id="publisher/model",
        revision="a" * 40,
        cache_dir=root,
        artifacts=(
            ModelArtifact("nested/model.bin", len(content), hashlib.sha256(content).hexdigest()),
        ),
    )


def test_cache_requires_complete_files_and_matching_marker(tmp_path):
    content = b"verified model"
    manifest = _manifest(tmp_path, content)
    target = tmp_path / "nested" / "model.bin"
    target.parent.mkdir()
    target.write_bytes(content)

    assert model_cache_status(manifest)[0] is False
    write_verification_marker(manifest)
    assert model_cache_status(manifest) == (True, f"verified revision {manifest.revision}")

    marker = json.loads((tmp_path / MARKER_FILENAME).read_text())
    marker["revision"] = "b" * 40
    (tmp_path / MARKER_FILENAME).write_text(json.dumps(marker))
    assert model_cache_status(manifest)[0] is False


def test_marker_creation_rejects_corrupt_file(tmp_path):
    manifest = _manifest(tmp_path)
    target = tmp_path / "nested" / "model.bin"
    target.parent.mkdir()
    target.write_bytes(b"wrong contents")

    with pytest.raises(ValueError, match="incomplete model cache"):
        write_verification_marker(manifest)


def test_download_is_pinned_atomic_and_verified(monkeypatch, tmp_path):
    content = b"verified model"
    manifest = _manifest(tmp_path, content)
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        Path(command[command.index("-o") + 1]).write_bytes(content)

    monkeypatch.setattr(model_download.subprocess, "run", fake_run)
    model_download.download_model(manifest, mirror="https://models.example")

    assert (tmp_path / "nested" / "model.bin").read_bytes() == content
    assert not (tmp_path / "nested" / "model.bin.part").exists()
    assert manifest.revision in commands[0][-1]
    assert "/resolve/main/" not in commands[0][-1]
    assert model_cache_status(manifest)[0] is True


def test_download_removes_failed_partial(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path)
    (tmp_path / MARKER_FILENAME).write_text("stale marker")

    def fake_run(command, **_kwargs):
        Path(command[command.index("-o") + 1]).write_bytes(b"wrong contents")

    monkeypatch.setattr(model_download.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="SHA-256"):
        model_download.download_model(manifest)
    assert not (tmp_path / "nested" / "model.bin").exists()
    assert not (tmp_path / "nested" / "model.bin.part").exists()
    assert not (tmp_path / MARKER_FILENAME).exists()

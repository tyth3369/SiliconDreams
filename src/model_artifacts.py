"""Pinned local-model manifests and cache integrity verification."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

MARKER_FILENAME = ".silicondreams-model.json"


@dataclass(frozen=True)
class ModelArtifact:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelManifest:
    model_id: str
    revision: str
    cache_dir: Path
    artifacts: tuple[ModelArtifact, ...]

    @property
    def fingerprint(self) -> str:
        payload = {
            "model_id": self.model_id,
            "revision": self.revision,
            "artifacts": [asdict(artifact) for artifact in self.artifacts],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


BGE_M3_MANIFEST = ModelManifest(
    model_id="BAAI/bge-m3",
    revision="5617a9f61b028005a4858fdac845db406aefb181",
    cache_dir=Path("~/.cache/silicondreams/models/bge-m3").expanduser(),
    artifacts=(
        ModelArtifact(
            "1_Pooling/config.json",
            191,
            "e54c164a07274f2eb45bb724f54a79d1efcc90c41573887cd9a29aeee0597352",
        ),
        ModelArtifact(
            "config.json", 687, "26159e7ad065073448460117eb24b7a4572f6f4e78eadff65dc0a11c052449fa"
        ),
        ModelArtifact(
            "modules.json", 349, "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf"
        ),
        ModelArtifact(
            "pytorch_model.bin",
            2_271_145_830,
            "b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38",
        ),
        ModelArtifact(
            "sentence_bert_config.json",
            54,
            "eb9b44b13c0f52a3b3685c3b1cbdea1ba8b04bea123b98f61610048940776eb1",
        ),
        ModelArtifact(
            "sentencepiece.bpe.model",
            5_069_051,
            "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
        ),
        ModelArtifact(
            "special_tokens_map.json",
            964,
            "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835",
        ),
        ModelArtifact(
            "tokenizer.json",
            17_098_108,
            "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08",
        ),
        ModelArtifact(
            "tokenizer_config.json",
            444,
            "a62b2b6784f990259fddef5f16388693a8043be4f69179e6a5257eeb3f9abac4",
        ),
    ),
)

RERANKER_MANIFEST = ModelManifest(
    model_id="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
    revision="1427fd652930e4ba29e8149678df786c240d8825",
    cache_dir=Path("~/.cache/silicondreams/models/mmarco-reranker").expanduser(),
    artifacts=(
        ModelArtifact(
            "config.json", 891, "cc2cfe51aa3fd759d21d21acf5dfd6994aa67a3c9210636d22e143699d336c77"
        ),
        ModelArtifact(
            "model.safetensors",
            470_592_698,
            "5daeca2481a76b5976a2bdc32f0a78532b6716da4f8cd3ff59460ef8d2f359b4",
        ),
        ModelArtifact(
            "sentencepiece.bpe.model",
            5_069_051,
            "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
        ),
        ModelArtifact(
            "special_tokens_map.json",
            239,
            "378eb3bf733eb16e65792d7e3fda5b8a4631387ca04d2015199c4d4f22ae554d",
        ),
        ModelArtifact(
            "tokenizer.json",
            17_082_660,
            "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626",
        ),
        ModelArtifact(
            "tokenizer_config.json",
            435,
            "e7fbfbfa6347b4e414c1cee50d142e2c2f9a895dad68b068ae83a8b564c3837e",
        ),
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(path: Path, artifact: ModelArtifact, *, verify_hash: bool) -> bool:
    if not path.is_file() or path.stat().st_size != artifact.size:
        return False
    return not verify_hash or sha256_file(path) == artifact.sha256


def model_cache_status(
    manifest: ModelManifest,
    *,
    verify_hash: bool = False,
    require_marker: bool = True,
) -> tuple[bool, str]:
    for artifact in manifest.artifacts:
        path = manifest.cache_dir / artifact.path
        if not verify_artifact(path, artifact, verify_hash=verify_hash):
            check = "size/SHA-256" if verify_hash else "size"
            return False, f"{artifact.path} failed {check} verification"

    if require_marker:
        marker_path = manifest.cache_dir / MARKER_FILENAME
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, f"missing or invalid {MARKER_FILENAME}"
        if (
            marker.get("model_id") != manifest.model_id
            or marker.get("revision") != manifest.revision
            or marker.get("manifest_sha256") != manifest.fingerprint
        ):
            return False, "verification marker does not match pinned manifest"
    return True, f"verified revision {manifest.revision}"


def write_verification_marker(manifest: ModelManifest) -> Path:
    ready, detail = model_cache_status(manifest, verify_hash=True, require_marker=False)
    if not ready:
        raise ValueError(f"cannot mark incomplete model cache: {detail}")
    manifest.cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_id": manifest.model_id,
        "revision": manifest.revision,
        "manifest_sha256": manifest.fingerprint,
    }
    fd, temporary_name = tempfile.mkstemp(
        prefix=f"{MARKER_FILENAME}.", suffix=".tmp", dir=manifest.cache_dir
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(manifest.cache_dir / MARKER_FILENAME)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest.cache_dir / MARKER_FILENAME

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEWED_CHROMA_ADVISORIES = {
    "PYSEC-2026-311",
    "PYSEC-2026-3813",
    "PYSEC-2026-3814",
    "PYSEC-2026-3815",
}


def test_chromadb_remains_embedded_and_has_no_http_client():
    source = (ROOT / "src" / "vector_store.py").read_text(encoding="utf-8")
    assert "chromadb.PersistentClient(" in source
    assert "chromadb.HttpClient(" not in source


def test_compose_does_not_expose_a_chromadb_service():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    registry_override = (ROOT / "compose.registry.yaml").read_text(encoding="utf-8")
    app_block = compose.split("\n  caddy:", 1)[0]

    assert "\n  chroma:" not in compose.lower()
    assert "chroma run" not in compose.lower()
    assert '    expose:\n      - "8000"' in app_block
    assert "    ports:" not in app_block
    assert "    ports:" not in registry_override
    assert "SILICONDREAMS_IMAGE" in registry_override


def test_ci_ignores_only_reviewed_unfixed_chromadb_advisories():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    policy = (ROOT / "docs" / "security-advisories.md").read_text(encoding="utf-8")

    ignored = set(re.findall(r"--ignore-vuln\s+(PYSEC-\d{4}-\d+)", workflow))
    assert ignored == REVIEWED_CHROMA_ADVISORIES
    for advisory in REVIEWED_CHROMA_ADVISORIES:
        assert advisory in policy


def test_linux_uses_hashed_cpu_only_pytorch_dependency():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'index = "pytorch-cpu", marker = "sys_platform == \'linux\'"' in project
    assert 'url = "https://download.pytorch.org/whl/cpu"' in project
    assert "explicit = true" in project
    assert re.search(
        r"^torch==[^\s;]+\+cpu ; sys_platform == 'linux'",
        requirements,
        re.MULTILINE,
    )
    assert "--hash=sha256:" in requirements
    assert not re.search(r"^(?:nvidia-|cuda-|triton==)", requirements, re.MULTILINE)
    assert "pip-audit --disable-pip -r requirements.txt" in workflow
    assert "assert torch.version.cuda is None" in workflow


def test_docker_build_cache_is_not_persisted_in_runtime_image():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "UV_LINK_MODE=copy" in dockerfile
    assert dockerfile.count("--mount=type=cache,id=uv-cache,target=/root/.cache/uv") == 2
    assert "RUN uv sync" not in dockerfile


def test_public_deployment_workflow_is_credential_free():
    workflow = (ROOT / ".github" / "workflows" / "verify-deployment.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "expected_ip:" in workflow
    assert "python scripts/verify_deployment.py" in workflow
    assert '--expected-version "$EXPECTED_VERSION"' in workflow
    assert "secrets." not in workflow
    assert "contents: read" in workflow

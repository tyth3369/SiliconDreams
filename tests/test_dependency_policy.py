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
    app_block = compose.split("\n  caddy:", 1)[0]

    assert "\n  chroma:" not in compose.lower()
    assert "chroma run" not in compose.lower()
    assert '    expose:\n      - "8000"' in app_block
    assert "    ports:" not in app_block


def test_ci_ignores_only_reviewed_unfixed_chromadb_advisories():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    policy = (ROOT / "docs" / "security-advisories.md").read_text(encoding="utf-8")

    ignored = set(re.findall(r"--ignore-vuln\s+(PYSEC-\d{4}-\d+)", workflow))
    assert ignored == REVIEWED_CHROMA_ADVISORIES
    for advisory in REVIEWED_CHROMA_ADVISORIES:
        assert advisory in policy

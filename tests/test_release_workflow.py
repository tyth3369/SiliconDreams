from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_publishes_versioned_image_and_attestation():
    workflow = (ROOT / ".github" / "workflows" / "publish-image.yml").read_text(encoding="utf-8")

    assert 'tags:\n      - "v*"' in workflow
    assert "IMAGE_NAME: ghcr.io/tyth3369/silicondreams" in workflow
    assert "packages: write" in workflow
    assert "attestations: write" in workflow
    assert "id-token: write" in workflow
    assert "push: true" in workflow
    assert "type=ref,event=tag" in workflow
    assert "flavor: latest=false" in workflow
    assert "type=raw,value=latest,enable=${{ !contains(github.ref_name, '-') }}" in workflow
    assert "http://127.0.0.1:8765/healthz" in workflow
    assert "subject-digest: ${{ steps.push.outputs.digest }}" in workflow


def test_registry_compose_requires_an_explicit_image():
    override = (ROOT / "compose.registry.yaml").read_text(encoding="utf-8")

    assert "SILICONDREAMS_IMAGE:?" in override
    assert "pull_policy: always" in override
    assert ":latest" not in override

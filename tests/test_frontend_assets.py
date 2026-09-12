import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SHA256 = {
    "static/vendor/htmx-1.9.12.min.js": "449317ade7881e949510db614991e195c3a099c4c791c24dacec55f9f4a2a452",
    "static/vendor/marked-15.0.12.min.js": "3e7e7d7feb3e5d58cb6c804f68ab5c24cc7e5eb6270fd6e5cbb9124739217d0c",
    "static/vendor/dompurify-3.4.15.min.js": "f263b05369e050fa175d4ecb9c9358eb4253602d510297adfb31df48b2f1c4d5",
}


def test_vendored_browser_runtimes_match_reviewed_hashes():
    for relative_path, expected in EXPECTED_SHA256.items():
        payload = (ROOT / relative_path).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected


def test_frontend_css_uses_self_hosted_fonts_only():
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    assert "https://" not in css
    assert "/static/fonts/ibm-plex-mono-latin-400.woff2" in css
    assert "/static/fonts/ibm-plex-sans-latin-400.woff2" in css


def test_vendored_components_preserve_license_texts():
    license_dir = ROOT / "static/vendor/licenses"
    expected = {
        "htmx-1.9.12-0BSD.txt",
        "marked-15.0.12-MIT.md",
        "dompurify-3.4.15-MPL-2.0-OR-Apache-2.0.txt",
        "IBM-Plex-OFL-1.1.txt",
    }
    assert expected <= {path.name for path in license_dir.iterdir() if path.stat().st_size > 0}

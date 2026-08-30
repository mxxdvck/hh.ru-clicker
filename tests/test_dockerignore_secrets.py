from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _patterns() -> set[str]:
    return {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_runtime_secrets_are_excluded_from_docker_build_context():
    patterns = _patterns()

    assert "data/" in patterns
    assert "backups/" in patterns
    assert ".env" in patterns
    assert ".env.*" in patterns


def test_public_env_template_remains_available_to_build_context():
    patterns = _patterns()

    assert "!.env.example" in patterns

import subprocess
import tarfile
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPOSITORY_ROOT / "scripts" / "build-runtime-release.sh"
RUNTIME_REQUIREMENTS = REPOSITORY_ROOT / "requirements.txt"
DEVELOPER_REQUIREMENTS = REPOSITORY_ROOT / "requirements-dev.txt"
DOCKERFILE = REPOSITORY_ROOT / "Dockerfile"
AUDIO_LAB_REQUIREMENTS = {
    "aiohappyeyeballs",
    "aiosignal",
    "attrs",
    "frozenlist",
    "multidict",
    "yarl",
    "idna",
    "propcache",
}
GATEWAY_WEBSOCKET_REQUIREMENTS = {"aiohttp"}
REQUIRED_MEMBERS = {
    "main.py",
    "requirements.txt",
    "src/generated/byova_common_pb2.py",
    "src/generated/byova_common_pb2_grpc.py",
    "src/generated/health_pb2.py",
    "src/generated/health_pb2_grpc.py",
    "src/generated/voicevirtualagent_pb2.py",
    "src/generated/voicevirtualagent_pb2_grpc.py",
    "src/core/conversation_registry.py",
    "src/connectors/aws_lex_websocket_connector.py",
    "src/transports/__init__.py",
    "src/transports/websocket_adapter.py",
    "src/transports/websocket_models.py",
    "src/transports/websocket_server.py",
}
RUNTIME_SOURCE_FILES = {
    "src/runtime/__init__.py",
    "src/runtime/container_bootstrap.py",
    "src/runtime/healthcheck.py",
}
DEVELOPMENT_ONLY_REQUIREMENTS = {
    "black",
    "flake8",
    "mypy",
    "pytest",
    "pytest-asyncio",
    "ruff",
}
FORBIDDEN_DIRECTORIES = {"docs", "tests", "tools"}
FORBIDDEN_FILENAMES = {
    "requirements-dev.txt",
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}


def test_audio_lab_web_server_dependency_is_developer_only() -> None:
    runtime_requirements = RUNTIME_REQUIREMENTS.read_text(encoding="utf-8")
    developer_requirements = DEVELOPER_REQUIREMENTS.read_text(encoding="utf-8")

    assert "-r requirements.txt" in developer_requirements
    for requirement in GATEWAY_WEBSOCKET_REQUIREMENTS:
        assert requirement in runtime_requirements
        assert requirement in developer_requirements
    for requirement in AUDIO_LAB_REQUIREMENTS:
        assert requirement not in runtime_requirements
        assert requirement in developer_requirements
    for requirement in DEVELOPMENT_ONLY_REQUIREMENTS:
        assert requirement not in runtime_requirements
        assert requirement in developer_requirements


def test_container_runtime_helpers_are_part_of_the_runtime_source_tree() -> None:
    for relative_path in RUNTIME_SOURCE_FILES:
        assert (REPOSITORY_ROOT / relative_path).is_file()


def test_container_pins_matching_cpu_only_torch_packages() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert '"torch==2.11.0+cpu"' in dockerfile
    assert '"torchaudio==2.11.0+cpu"' in dockerfile
    assert "https://download.pytorch.org/whl/cpu" in dockerfile


def test_container_uses_digest_pinned_amazon_linux() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    expected_base = (
        "public.ecr.aws/amazonlinux/amazonlinux:2023-minimal@sha256:"
        "478c519817ce1c2cdc64700e4395775143446f8706706906b942960f0394ff2e"
    )
    assert dockerfile.count(f"FROM {expected_base}") == 2
    assert "python3.12" in dockerfile
    assert "tini" not in dockerfile


def test_runtime_release_contains_only_runtime_files(tmp_path: Path) -> None:
    archive_path = tmp_path / "byova-gateway-runtime.tar.gz"

    subprocess.run(
        [str(BUILD_SCRIPT), "--ref", "HEAD", "--output", str(archive_path)],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    with tarfile.open(archive_path, "r:gz") as archive:
        archive_members = archive.getmembers()
        members = {member.name for member in archive_members}

    assert REQUIRED_MEMBERS <= members
    assert any(name.startswith("config/") for name in members)
    assert any(name.startswith("proto/") for name in members)
    assert any(name.startswith("src/") for name in members)

    for member in members:
        path = PurePosixPath(member)
        assert not (FORBIDDEN_DIRECTORIES & set(path.parts))
        assert path.name not in FORBIDDEN_FILENAMES
        assert not any(part.startswith("._") for part in path.parts)

    assert all(not member.pax_headers for member in archive_members)

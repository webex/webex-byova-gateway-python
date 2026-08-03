import subprocess
import tarfile
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPOSITORY_ROOT / "scripts" / "build-runtime-release.sh"
REQUIRED_MEMBERS = {
    "main.py",
    "requirements.txt",
}
FORBIDDEN_DIRECTORIES = {"docs", "tests", "tools"}
FORBIDDEN_FILENAMES = {
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}


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
        members = {member.name for member in archive.getmembers()}

    assert REQUIRED_MEMBERS <= members
    assert any(name.startswith("config/") for name in members)
    assert any(name.startswith("proto/") for name in members)
    assert any(name.startswith("src/") for name in members)

    for member in members:
        path = PurePosixPath(member)
        assert not (FORBIDDEN_DIRECTORIES & set(path.parts))
        assert path.name not in FORBIDDEN_FILENAMES
        assert not any(part.startswith("._") for part in path.parts)

"""Build and smoke-test a wheel and sdist before copying them into dist/."""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(arguments, cwd=cwd, env=env, check=True)


def unpack_source(
    archive: Path, destination: Path, *, project_root: Path = ROOT
) -> Path:
    """Reject incomplete source archives before publishing any artifacts."""
    required = {
        "main.py",
        "run_tests.py",
        "pyproject.toml",
        "requirements.txt",
        "requirements-build.txt",
        "requirements-dev.txt",
    }
    required.update(
        path.relative_to(project_root).as_posix()
        for path in (project_root / "tests").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    prefix = archive.name.removesuffix(".tar.gz")
    with tarfile.open(archive) as package:
        members = {member.name for member in package.getmembers() if member.isfile()}
        missing = sorted(name for name in required if f"{prefix}/{name}" not in members)
        if missing:
            raise ValueError("Source archive is missing: " + ", ".join(missing))
        package.extractall(destination, filter="data")
    return destination / prefix


def main() -> int:
    try:
        run(sys.executable, "run_tests.py")
        run(sys.executable, "-m", "pip", "check")
        with tempfile.TemporaryDirectory(prefix="gmscrap-release-") as temporary:
            workspace = Path(temporary)
            artifacts = workspace / "artifacts"
            run(
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(artifacts),
            )
            # Build's default workflow builds the wheel from the generated sdist.
            wheel = next(artifacts.glob("*.whl"))
            source = unpack_source(
                next(artifacts.glob("*.tar.gz")), workspace / "source"
            )
            environment = workspace / "venv"
            venv.EnvBuilder(with_pip=True).create(environment)
            scripts = environment / ("Scripts" if os.name == "nt" else "bin")
            python = scripts / ("python.exe" if os.name == "nt" else "python")
            command = scripts / ("gmscrap.exe" if os.name == "nt" else "gmscrap")
            pdf_command = scripts / (
                "gmscrap-pdf.exe" if os.name == "nt" else "gmscrap-pdf"
            )
            clean_env = os.environ.copy()
            clean_env.pop("PYTHONPATH", None)
            clean_env.pop("PYTHONHOME", None)
            clean_env["PYTHONNOUSERSITE"] = "1"
            clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
            clean_env["PYTHONUTF8"] = "1"
            run(
                str(python),
                "-m",
                "pip",
                "install",
                str(wheel),
                cwd=workspace,
                env=clean_env,
            )
            run(str(python), "-m", "pip", "check", cwd=workspace, env=clean_env)
            for arguments in (
                (str(command), "--version"),
                (str(command), "--help"),
                (str(pdf_command), "--help"),
                (str(python), "-m", "my_package", "--version"),
                (str(python), "-m", "my_package.main", "--version"),
                (str(python), str(source / "main.py"), "--version"),
            ):
                run(*arguments, cwd=workspace, env=clean_env)
            # Exercise installed code away from src/, with a controlled provider.
            run(
                str(python),
                "-c",
                "import json; from unittest.mock import patch; "
                "from my_package.services.scrap import ScrapService; "
                "p = patch('my_package.infrastructure.overpass.requests.post'); "
                "post = p.start(); "
                "post.return_value.json.return_value = {'elements': "
                "[{'type': 'node', 'id': 1, 'lat': 49, 'lon': 24}]}; "
                "result = json.loads(ScrapService().search('49,24', 'cafe', 1)); "
                "assert result[0]['osm_id'] == 'node/1'; "
                "assert result[0]['website'] is None; p.stop()",
                cwd=workspace,
                env=clean_env,
            )
            # Install the published extras with pinned test dependencies, then
            # exercise the installed wheel using tests shipped in the sdist.
            # cwd and PYTHONPATH must not expose either checkout's src directory.
            run(
                str(python),
                "-m",
                "pip",
                "install",
                "-r",
                str(source / "requirements-dev.txt"),
                f"{wheel}[api,pdf]",
                cwd=workspace,
                env=clean_env,
            )
            run(str(python), "-m", "pip", "check", cwd=workspace, env=clean_env)
            run(str(python), "-m", "uvicorn", "--version", cwd=workspace, env=clean_env)
            run(
                str(python),
                "-c",
                "import sys; from pathlib import Path; import my_package; "
                "assert Path(my_package.__file__).resolve().is_relative_to("
                "Path(sys.prefix).resolve()), my_package.__file__",
                cwd=workspace,
                env=clean_env,
            )
            run(
                str(python),
                "-m",
                "unittest",
                "discover",
                "-s",
                str(source / "tests"),
                "-v",
                cwd=workspace,
                env=clean_env,
            )
            destination = ROOT / "dist"
            destination.mkdir(exist_ok=True)
            checksums = []
            for artifact in sorted(artifacts.iterdir()):
                digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                shutil.copy2(artifact, destination / artifact.name)
                checksums.append(f"{digest}  {artifact.name}\n")
            (destination / "SHA256SUMS").write_text(
                "".join(checksums), encoding="utf-8"
            )
    except (
        subprocess.CalledProcessError,
        OSError,
        ValueError,
        tarfile.TarError,
    ) as error:
        print(f"Release validation failed: {error}", file=sys.stderr)
        return 1
    print(f"Validated release artifacts: {ROOT / 'dist'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

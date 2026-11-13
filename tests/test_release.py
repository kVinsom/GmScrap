"""Release archives must preserve the tests and their runtime fixtures."""

import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "project_release", ROOT / "scripts" / "release.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class SourceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.project = self.directory / "project"
        self.fixture = "tests/fixtures/tls/server.pem"
        fixture = self.project / self.fixture
        fixture.parent.mkdir(parents=True)
        fixture.write_bytes(b"test certificate")
        self.files = {
            name: b""
            for name in (
                "main.py",
                "run_tests.py",
                "pyproject.toml",
                "requirements.txt",
                "requirements-build.txt",
                "requirements-dev.txt",
            )
        }
        self.files[self.fixture] = fixture.read_bytes()

    def archive(self, files):
        archive = self.directory / "gmscrap-0.1.0.tar.gz"
        with tarfile.open(archive, "w:gz") as package:
            for name, content in files.items():
                member = tarfile.TarInfo("gmscrap-0.1.0/" + name)
                member.size = len(content)
                package.addfile(member, io.BytesIO(content))
        return archive

    def test_complete_archive_extracts_fixture(self):
        source = release.unpack_source(
            self.archive(self.files),
            self.directory / "unpacked",
            project_root=self.project,
        )
        self.assertEqual((source / self.fixture).read_bytes(), b"test certificate")

    def test_missing_fixture_or_runner_rejects_archive_before_extraction(self):
        for missing in (self.fixture, "run_tests.py"):
            with self.subTest(missing=missing):
                archive = self.archive(
                    {name: data for name, data in self.files.items() if name != missing}
                )
                destination = self.directory / "unpacked"
                with self.assertRaises(ValueError) as error:
                    release.unpack_source(
                        archive, destination, project_root=self.project
                    )
                self.assertIn(missing, str(error.exception))
                self.assertFalse(destination.exists())

    def test_archive_cannot_write_outside_destination(self):
        files = dict(self.files, **{"../../escaped.txt": b"unexpected"})
        with self.assertRaises(tarfile.FilterError):
            release.unpack_source(
                self.archive(files),
                self.directory / "unpacked",
                project_root=self.project,
            )
        self.assertFalse((self.directory / "escaped.txt").exists())

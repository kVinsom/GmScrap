import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from my_package.handlers.scrap.scrap import ScrapHandler
from my_package.repositories.scrap import ScrapRepository
from my_package.services.scrap import ScrapService

PDF = b"%PDF-1.7\nexample bytes\n%%EOF"


class PdfStorageTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.database = Path(directory) / "pdfs.sqlite3"
        self.repository = ScrapRepository(self.database)
        self.handler = ScrapHandler(
            ScrapService(
                repository=self.repository, geocoder=Mock(), place_source=Mock()
            )
        )

    def test_lazy_creation_and_persistent_round_trip(self):
        self.assertFalse(self.database.exists())
        self.handler.save_pdf("Lviv.pdf", PDF)
        reopened = ScrapRepository(self.database)
        self.assertEqual(reopened.get_pdf("Lviv.pdf"), PDF)
        self.assertEqual(self.handler.get_pdf("Lviv.pdf"), PDF)
        self.assertEqual(self.handler.get_all_pdfs(), {"Lviv.pdf": PDF})

    def test_duplicate_name_does_not_replace_original(self):
        self.handler.save_pdf("coffee", PDF)
        with self.assertRaises(ValueError):
            self.handler.save_pdf("coffee", b"%PDF-1.7\nreplacement")
        self.assertEqual(self.handler.get_pdf("coffee"), PDF)

    def test_get_all_and_delete_by_exact_name(self):
        name = "coffee'; DROP TABLE pdf_files; --"
        self.assertEqual(self.handler.get_all_pdfs(), {})
        self.assertIsNone(self.handler.get_pdf("missing"))
        self.assertFalse(self.handler.delete_pdf("missing"))
        self.handler.save_pdf(name, PDF)
        self.handler.save_pdf("other", PDF + b"\n")
        self.assertEqual(self.handler.get_all_pdfs(), {name: PDF, "other": PDF + b"\n"})
        self.assertTrue(self.handler.delete_pdf(name))
        self.assertFalse(self.handler.delete_pdf(name))
        self.assertIsNone(self.handler.get_pdf(name))
        self.assertEqual(self.handler.get_all_pdfs(), {"other": PDF + b"\n"})

    def test_invalid_input_does_not_create_database(self):
        for name in (None, 123, "", "   "):
            for operation in (self.handler.get_pdf, self.handler.delete_pdf):
                with (
                    self.subTest(name=name),
                    self.assertRaises((TypeError, ValueError)),
                ):
                    operation(name)
            with self.assertRaises((TypeError, ValueError)):
                self.handler.save_pdf(name, PDF)
        for content in (None, "text", b"", b"not PDF"):
            with self.assertRaises((TypeError, ValueError)):
                self.handler.save_pdf("coffee", content)
        self.assertFalse(self.database.exists())

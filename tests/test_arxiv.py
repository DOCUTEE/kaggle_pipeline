"""Tests for arXiv pipeline pieces — offline, no network, no MinIO/DB needed.

Run:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.sources.arxiv import _clean_ws, _safe_id  # noqa: E402


class TestArxivHelpers(unittest.TestCase):
    def test_clean_ws(self):
        self.assertEqual(_clean_ws("  Deep\n  Learning\t  "), "Deep Learning")
        self.assertEqual(_clean_ws(""), "")

    def test_safe_id_new_style(self):
        self.assertEqual(_safe_id("2609.19146v1"), "2609.19146v1")

    def test_safe_id_old_style_slash(self):
        safe = _safe_id("hep-th/9901001v1")
        self.assertNotIn("/", safe)
        self.assertIn("hep-th", safe)


class TestArxivFieldMapping(unittest.TestCase):
    def test_fields(self):
        from pipeline.build import _arxiv_field

        self.assertEqual(_arxiv_field("cs.AI"), "Computer Science")
        self.assertEqual(_arxiv_field("math.CO"), "Mathematics")
        self.assertEqual(_arxiv_field("quant-ph"), "Physics")
        self.assertEqual(_arxiv_field("astro-ph"), "Physics")
        self.assertEqual(_arxiv_field("q-bio.NC"), "Quantitative Biology")
        self.assertEqual(_arxiv_field("stat.ML"), "Statistics")
        self.assertEqual(_arxiv_field("eess.SP"), "EESS")
        self.assertEqual(_arxiv_field("econ.EM"), "Economics")
        self.assertEqual(_arxiv_field(""), "Physics")

    def test_keywords(self):
        from pipeline.build import _arxiv_top_keywords

        top = dict(_arxiv_top_keywords(["Quantum Machine Learning for Quantum Systems",
                                        "Deep Learning for Vision"]))
        self.assertIn("quantum", top)
        self.assertNotIn("for", top)  # stopword
        self.assertNotIn("paper", top)


class TestSourceRegistry(unittest.TestCase):
    def test_all_sources_registered(self):
        from pipeline.sources import ALL_SOURCES, get_source

        self.assertIn("arxiv", ALL_SOURCES)
        self.assertIn("itviec", ALL_SOURCES)
        self.assertIn("topcv", ALL_SOURCES)
        for name in ALL_SOURCES:
            src = get_source(name)
            self.assertEqual(src.name, name)

    def test_settings_match_registry(self):
        from pipeline import settings
        from pipeline.sources import ALL_SOURCES

        self.assertEqual(set(settings.SOURCES), set(ALL_SOURCES))

    def test_arxiv_manual_schedule(self):
        from pipeline import settings

        self.assertEqual(settings.get_source("arxiv").schedule, "manual")


class TestMinioFallback(unittest.TestCase):
    def test_unreachable_minio_returns_file_uri(self):
        import os
        import tempfile

        from pipeline import minio_store

        os.environ["MINIO_ENDPOINT"] = "localhost:9"  # cổng chết chắc chắn
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(b"%PDF-1.4 test")
                path = Path(f.name)
            ok, loc = minio_store.upload_file(path, "arxiv/test.pdf")
            self.assertFalse(ok)
            self.assertTrue(loc.startswith("file://"))
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

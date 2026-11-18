"""Regression checks for the non-executing PySide6 source inspector.

Run with: python -m unittest discover -s tests -p "test_*.py"
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from python_importer import analyze, replace_literal, library_split_sizes, patch_library_split_sizes


class ImporterTests(unittest.TestCase):
    def test_imagescraper_fixture(self):
        source = (ROOT / "tests" / "ImageScraper" / "gui.py").read_text(encoding="utf-8")
        elements = analyze(source)
        names = {(e.section, e.key) for e in elements}
        for expected in [
            ("MainWindow._build", "sidebar"),
            ("MainWindow._library", "split"),
            ("MainWindow._library", "self.table"),
            ("MainWindow._library", "self.image_viewer"),
            ("ImageViewer.__init__", "self.image_label"),
            ("ImageViewer.__init__", "self.download_btn"),
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, names)
        self.assertGreater(len(elements), 40)
        # The test imports only python_importer, never the user's ImageScraper module.

    def test_custom_widget_subclasses(self):
        source = """class BasePanel(QWidget):
    pass
class ImageViewer(BasePanel):
    pass
class ScrapeWorker(QRunnable):
    pass
class Window:
    def build(self):
        self.viewer = ImageViewer()
        self.worker = ScrapeWorker()
"""
        elements = analyze(source)
        self.assertIn(("Window.build", "self.viewer"), {(e.section, e.key) for e in elements})
        self.assertNotIn(("Window.build", "self.worker"), {(e.section, e.key) for e in elements})

    def test_literal_patch_preserves_surrounding_code(self):
        source = '''class Window:
    def _build(self):
        sidebar = QFrame()
        sidebar.setFixedWidth(215)
        label = QLabel("◈  ImageScraper")
'''
        elements = analyze(source)
        sidebar = next(e for e in elements if e.key == "sidebar")
        node = next(n for title, n, _ in sidebar.methods if title == "Width")
        patched = replace_literal(source, node, "275")
        ast.parse(patched)
        self.assertIn("setFixedWidth(275)", patched)
        self.assertIn('QLabel("◈  ImageScraper")', patched)

    def test_invalid_edit_is_rejected(self):
        source = "class W:\n def page(self):\n  box = QFrame()\n  box.setFixedWidth(100)\n"
        box = next(e for e in analyze(source) if e.key == "box")
        node = box.methods[0][1]
        with self.assertRaises(ValueError):
            replace_literal(source, node, "not a number")

    def test_imagescraper_visual_splitter_round_trip(self):
        source = (ROOT / "tests" / "ImageScraper" / "gui.py").read_text(encoding="utf-8")
        self.assertEqual(library_split_sizes(source), (450, 730))
        updated = patch_library_split_sizes(source, 360, 820)
        self.assertEqual(library_split_sizes(updated), (360, 820))
        self.assertIn("split.setSizes([360,820])", updated)
        self.assertIn("split.setSizes([450,730])", source)
        ast.parse(updated)
        self.assertEqual(updated.replace("split.setSizes([360,820])", "split.setSizes([450,730])"), source)

    def test_visual_splitter_rejects_unsupported_layout(self):
        source = "class Example:\n def build(self):\n  split = QSplitter()\n  split.setSizes([3,4])\n"
        self.assertIsNone(library_split_sizes(source))
        with self.assertRaises(ValueError):
            patch_library_split_sizes(source, 100, 200)

    def test_splitter_sizes_edit(self):
        source = "class W:\n def page(self):\n  split = QSplitter()\n  split.setSizes([450,730])\n"
        split = next(e for e in analyze(source) if e.key == "split")
        self.assertEqual([label for label, _, _ in split.methods], ["Splitter size 1", "Splitter size 2"])
        updated = replace_literal(source, split.methods[0][1], "360")
        self.assertIn("setSizes([360,730])", updated)


if __name__ == "__main__":
    unittest.main()

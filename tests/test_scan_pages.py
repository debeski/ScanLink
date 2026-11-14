import tracemalloc
import unittest

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

import scanner

DPI = 150
SIZE = (int(8.27 * DPI), int(11.69 * DPI))
DECODED_PAGE_BYTES = SIZE[0] * SIZE[1] * 3


def printed_page():
    page = Image.new("L", SIZE, 255)
    draw = ImageDraw.Draw(page)
    for y in range(0, SIZE[1], DPI // 6):
        draw.line((DPI // 2, y, SIZE[0] - DPI // 2, y), fill=0, width=2)
    return page


class FakeTwainImage:
    def save(self, path):
        printed_page().save(path, format="BMP")

    def close(self):
        pass


class FakeSource:
    def __init__(self, pages):
        self.pages = pages

    def acquire_natively(self, after, before, show_ui, modal):
        for index in range(self.pages):
            before(None)
            after(FakeTwainImage(), index < self.pages - 1)

    def acquire_file(self, before, after, show_ui, modal):
        for index in range(self.pages):
            path = before(None)
            printed_page().save(path, format="BMP")
            after(index < self.pages - 1)


@unittest.skipIf(Image is None or scanner.canvas is None, "Pillow/ReportLab missing")
class ScanPageMemoryTests(unittest.TestCase):
    def acquire(self, mode, pages=3):
        manager = scanner.ScannerManager()
        captured = []
        progress = []
        acquire = getattr(manager, f"_acquire_via_{mode}_transfer")
        acquire(
            FakeSource(pages),
            captured,
            lambda status, **data: progress.append((status, data["page_count"])),
            None,
            False,
        )
        self.assertEqual(progress[-1], ("page_scanned", pages))
        return manager, captured

    def test_captured_pages_are_kept_compressed(self):
        for mode in ("native", "file"):
            with self.subTest(mode=mode):
                _, captured = self.acquire(mode)
                self.assertEqual(len(captured), 3)
                for page in captured:
                    self.assertIsInstance(page, bytes)
                    self.assertTrue(page.startswith(b"\xff\xd8"))
                    self.assertLess(len(page), DECODED_PAGE_BYTES // 10)

    def test_pdf_embeds_page_jpegs_without_decoding_them(self):
        manager, captured = self.acquire("native", pages=4)
        tracemalloc.start()
        try:
            pdf = manager._create_pdf(captured).getvalue()
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, DECODED_PAGE_BYTES)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(pdf.count(b"/DCTDecode"), 4)
        self.assertEqual(pdf.count(b"/Type /Page\n"), 4)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import unittest

from PIL import Image

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import MAX_IMAGE_BYTES
from ocr.scanner import compress_image, discover_files, prepare_batch


class TestCompressImage(unittest.TestCase):
    """Test image compression under the 5MB API limit."""

    def test_large_image_compresses_under_limit(self):
        """A 4000x3000 image must compress to under MAX_IMAGE_BYTES."""
        img = Image.new("RGB", (4000, 3000), color=(128, 64, 200))
        result = compress_image(img)
        self.assertIsInstance(result, bytes)
        self.assertLess(len(result), MAX_IMAGE_BYTES)

    def test_image_from_file_path(self):
        """compress_image works when given a file path string."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img = Image.new("RGB", (4000, 3000), color=(100, 150, 200))
            img.save(f, format="JPEG", quality=95)
            path = f.name
        try:
            result = compress_image(path)
            self.assertIsInstance(result, bytes)
            self.assertLess(len(result), MAX_IMAGE_BYTES)
        finally:
            os.unlink(path)

    def test_exif_transpose_no_crash_without_exif(self):
        """Images without EXIF data should not crash exif_transpose."""
        img = Image.new("RGB", (800, 600), color=(255, 0, 0))
        # No EXIF data at all — must not raise
        result = compress_image(img)
        self.assertIsInstance(result, bytes)

    def test_rgba_image_converts(self):
        """RGBA images (e.g. PNG with transparency) should convert to RGB."""
        img = Image.new("RGBA", (2000, 1500), color=(255, 0, 0, 128))
        result = compress_image(img)
        self.assertIsInstance(result, bytes)
        self.assertLess(len(result), MAX_IMAGE_BYTES)

    def test_small_image_not_upscaled(self):
        """An image smaller than max_dim should not be upscaled."""
        img = Image.new("RGB", (800, 600), color=(0, 255, 0))
        result = compress_image(img)
        # Verify the result is valid JPEG
        from io import BytesIO
        out = Image.open(BytesIO(result))
        self.assertEqual(out.size, (800, 600))


class TestDiscoverFiles(unittest.TestCase):
    """Test file discovery with various extensions and sort modes."""

    def test_finds_uppercase_jpg(self):
        """Must find .JPG files (iPhone default extension)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files with various extensions
            for name in ["photo.JPG", "scan.jpg", "doc.PDF", "notes.png"]:
                path = os.path.join(tmpdir, name)
                if name.endswith((".JPG", ".jpg", ".png")):
                    Image.new("RGB", (10, 10)).save(path)
                else:
                    open(path, "wb").write(b"%PDF-fake")

            files = discover_files(tmpdir)
            found_names = {os.path.basename(f["filepath"]) for f in files}
            self.assertIn("photo.JPG", found_names)
            self.assertIn("scan.jpg", found_names)
            self.assertIn("doc.PDF", found_names)
            self.assertIn("notes.png", found_names)
            self.assertEqual(len(files), 4)

    def test_skips_hidden_files(self):
        """Files starting with . should be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Image.new("RGB", (10, 10)).save(os.path.join(tmpdir, ".hidden.jpg"))
            Image.new("RGB", (10, 10)).save(os.path.join(tmpdir, "visible.jpg"))

            files = discover_files(tmpdir)
            self.assertEqual(len(files), 1)
            self.assertIn("visible.jpg", os.path.basename(files[0]["filepath"]))

    def test_sort_by_name(self):
        """Files sorted alphabetically by name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["charlie.jpg", "alpha.jpg", "bravo.jpg"]:
                Image.new("RGB", (10, 10)).save(os.path.join(tmpdir, name))

            files = discover_files(tmpdir, sort_by="name")
            names = [os.path.basename(f["filepath"]) for f in files]
            self.assertEqual(names, ["alpha.jpg", "bravo.jpg", "charlie.jpg"])


class TestPrepareBatch(unittest.TestCase):
    """Test batch preparation and sequencing."""

    def test_empty_directory(self):
        """Empty input dir should return empty list, not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = prepare_batch(tmpdir)
            self.assertEqual(result, [])

    def test_batch_with_images(self):
        """Batch with image files should have correct structure and sequencing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, name in enumerate(["a.jpg", "b.jpg"]):
                img = Image.new("RGB", (4000, 3000), color=(i * 50, 100, 150))
                img.save(os.path.join(tmpdir, name), quality=95)

            batch = prepare_batch(tmpdir, sort_by="name")
            self.assertEqual(len(batch), 2)

            # Check sequence numbers
            self.assertEqual(batch[0]["sequence"], 1)
            self.assertEqual(batch[1]["sequence"], 2)

            # Check structure
            for entry in batch:
                self.assertIn("sequence", entry)
                self.assertIn("source_file", entry)
                self.assertIn("source_page", entry)
                self.assertIn("source_type", entry)
                self.assertIn("image_bytes", entry)
                self.assertIn("original_size", entry)
                self.assertIn("compressed_size", entry)
                self.assertEqual(entry["source_type"], "image")
                self.assertEqual(entry["source_page"], 1)
                self.assertLess(entry["compressed_size"], MAX_IMAGE_BYTES)


if __name__ == "__main__":
    unittest.main()

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ocr.transcriber import (
    _checkpoint_basename,
    _find_completed_sequences,
    _save_checkpoint,
    transcribe_batch,
    transcribe_page,
)


def _make_page_entry(sequence=1, source_file="test.jpg", source_page=1):
    """Create a minimal page_entry dict for testing."""
    return {
        "sequence": sequence,
        "source_file": source_file,
        "source_page": source_page,
        "source_type": "image",
        "image_bytes": b"\xff\xd8\xff\xe0" + b"\x00" * 100,  # fake JPEG header
        "original_size": 1000,
        "compressed_size": 104,
    }


def _mock_api_response(text="Hello world\n\nCONFIDENCE: 85%", input_tokens=500, output_tokens=200):
    """Create a mock Anthropic API response."""
    resp = MagicMock()
    content_block = MagicMock()
    content_block.text = text
    resp.content = [content_block]
    resp.usage = MagicMock()
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    return resp


class TestTranscribePage(unittest.TestCase):

    def test_successful_transcription(self):
        """Mock a successful API call and verify result structure."""
        client = MagicMock()
        client.messages.create.return_value = _mock_api_response()

        page = _make_page_entry()
        result = transcribe_page(page, total_pages=5, mode="handwritten", client=client)

        self.assertEqual(result["status"], "ok")
        self.assertIn("Hello world", result["text"])
        self.assertEqual(result["confidence"], "85%")
        self.assertEqual(result["tokens_used"], 700)
        self.assertIsNone(result["error_message"])
        self.assertEqual(result["sequence"], 1)
        # image_bytes should NOT be in result
        self.assertNotIn("image_bytes", result)

    def test_api_error_handling(self):
        """API exceptions should be caught, not crash."""
        client = MagicMock()
        client.messages.create.side_effect = Exception("Rate limit exceeded")

        page = _make_page_entry()
        result = transcribe_page(page, total_pages=1, client=client)

        self.assertEqual(result["status"], "error")
        self.assertIn("Rate limit", result["error_message"])
        self.assertEqual(result["tokens_used"], 0)

    def test_empty_response(self):
        """Very short responses should be flagged as empty."""
        client = MagicMock()
        client.messages.create.return_value = _mock_api_response(text="ok")

        page = _make_page_entry()
        result = transcribe_page(page, total_pages=1, client=client)

        self.assertEqual(result["status"], "empty")

    def test_no_confidence_line(self):
        """Result should handle missing confidence gracefully."""
        client = MagicMock()
        client.messages.create.return_value = _mock_api_response(text="Some long transcription text here.")

        page = _make_page_entry()
        result = transcribe_page(page, total_pages=1, client=client)

        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["confidence"])

    def test_mode_options(self):
        """All three modes should work without error."""
        for mode in ["handwritten", "printed", "mixed"]:
            client = MagicMock()
            client.messages.create.return_value = _mock_api_response()
            page = _make_page_entry()
            result = transcribe_page(page, total_pages=1, mode=mode, client=client)
            self.assertEqual(result["status"], "ok")


class TestCheckpointing(unittest.TestCase):

    def test_checkpoint_basename_format(self):
        """Checkpoint names should follow seq_NNN__filename__page_N pattern."""
        page = _make_page_entry(sequence=3, source_file="Book Mar 23.pdf", source_page=2)
        basename = _checkpoint_basename(page)
        self.assertEqual(basename, "seq_003__Book_Mar_23__page_2")

    def test_checkpoint_saves_files(self):
        """Checkpoint should create .txt and .json files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = {
                "sequence": 1,
                "source_file": "test.jpg",
                "source_page": 1,
                "source_type": "image",
                "text": "Hello world\nCONFIDENCE: 90%",
                "confidence": "90%",
                "tokens_used": 500,
                "status": "ok",
                "error_message": None,
                "original_size": 1000,
                "compressed_size": 200,
            }
            _save_checkpoint(result, tmpdir)

            txt_path = os.path.join(tmpdir, "seq_001__test__page_1.txt")
            json_path = os.path.join(tmpdir, "seq_001__test__page_1.json")

            self.assertTrue(os.path.exists(txt_path))
            self.assertTrue(os.path.exists(json_path))

            with open(txt_path) as f:
                self.assertIn("Hello world", f.read())

            with open(json_path) as f:
                data = json.load(f)
                self.assertEqual(data["status"], "ok")
                self.assertEqual(data["confidence"], "90%")

    def test_resume_skips_completed(self):
        """Batch should skip pages with existing ok checkpoints."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake checkpoint for page 1
            checkpoint = {
                "sequence": 1,
                "source_file": "test.jpg",
                "source_page": 1,
                "source_type": "image",
                "text": "Already done",
                "confidence": "95%",
                "tokens_used": 300,
                "status": "ok",
                "error_message": None,
                "original_size": 1000,
                "compressed_size": 200,
            }
            with open(os.path.join(tmpdir, "seq_001__test__page_1.json"), "w") as f:
                json.dump(checkpoint, f)
            with open(os.path.join(tmpdir, "seq_001__test__page_1.txt"), "w") as f:
                f.write("Already done")

            completed = _find_completed_sequences(tmpdir)
            self.assertIn(1, completed)

    def test_resume_ignores_failed(self):
        """Failed checkpoints should NOT be in completed set (will retry)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint = {"sequence": 1, "status": "error"}
            with open(os.path.join(tmpdir, "seq_001__test__page_1.json"), "w") as f:
                json.dump(checkpoint, f)

            completed = _find_completed_sequences(tmpdir)
            self.assertNotIn(1, completed)


class TestTranscribeBatch(unittest.TestCase):

    @patch("ocr.transcriber.anthropic.Anthropic")
    @patch("ocr.transcriber.time.sleep")
    def test_batch_runs_and_checkpoints(self, mock_sleep, mock_anthropic_cls):
        """Batch should transcribe all pages and save checkpoints."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_api_response()
        mock_anthropic_cls.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmpdir:
            pages = [_make_page_entry(sequence=i) for i in range(1, 4)]
            results = transcribe_batch(pages, output_dir=tmpdir)

            self.assertEqual(len(results), 3)
            self.assertTrue(all(r["status"] == "ok" for r in results))

            # Check checkpoints were created
            json_files = [f for f in os.listdir(tmpdir) if f.endswith(".json")]
            txt_files = [f for f in os.listdir(tmpdir) if f.endswith(".txt")]
            self.assertEqual(len(json_files), 3)
            self.assertEqual(len(txt_files), 3)

    @patch("ocr.transcriber.anthropic.Anthropic")
    @patch("ocr.transcriber.time.sleep")
    def test_batch_resumes_from_checkpoint(self, mock_sleep, mock_anthropic_cls):
        """Batch should skip already-completed pages on resume."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_api_response()
        mock_anthropic_cls.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-create checkpoint for page 1
            checkpoint = {
                "sequence": 1,
                "source_file": "test.jpg",
                "source_page": 1,
                "source_type": "image",
                "text": "Already done",
                "confidence": "95%",
                "tokens_used": 300,
                "status": "ok",
                "error_message": None,
                "original_size": 1000,
                "compressed_size": 104,
            }
            with open(os.path.join(tmpdir, "seq_001__test__page_1.json"), "w") as f:
                json.dump(checkpoint, f)
            with open(os.path.join(tmpdir, "seq_001__test__page_1.txt"), "w") as f:
                f.write("Already done")

            pages = [_make_page_entry(sequence=i) for i in range(1, 3)]
            results = transcribe_batch(pages, output_dir=tmpdir)

            # API should only be called for page 2 (page 1 was cached)
            self.assertEqual(mock_client.messages.create.call_count, 1)
            self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.refiner import chunk_pages, refine_chunk, refine_transcript, _assemble_chunk_text


def _make_page(sequence, text="This is some valid transcription text for testing.", status="ok",
               source_file="doc.pdf", source_page=None):
    """Create a minimal page_entry dict for testing."""
    return {
        "sequence": sequence,
        "source_file": source_file,
        "source_page": source_page or sequence,
        "source_type": "pdf",
        "text": text,
        "confidence": "90%",
        "tokens_used": 100,
        "status": status,
        "error_message": None,
        "original_size": 5000,
        "compressed_size": 1000,
    }


def _mock_refine_response(text="Cleaned up text.", input_tokens=300, output_tokens=150):
    resp = MagicMock()
    content_block = MagicMock()
    content_block.text = text
    resp.content = [content_block]
    resp.usage = MagicMock()
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    return resp


class TestChunkPages(unittest.TestCase):

    def test_groups_into_correct_chunks(self):
        """12 pages with chunk_size=5 should produce 3 chunks (5, 5, 2)."""
        pages = [_make_page(i) for i in range(1, 13)]
        chunks = chunk_pages(pages, chunk_size=5)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), 5)
        self.assertEqual(len(chunks[1]), 5)
        self.assertEqual(len(chunks[2]), 2)

    def test_single_chunk_for_small_batch(self):
        """3 pages with default chunk_size=10 should produce 1 chunk."""
        pages = [_make_page(i) for i in range(1, 4)]
        chunks = chunk_pages(pages, chunk_size=10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 3)

    def test_filters_error_pages(self):
        """Pages with status != 'ok' should be excluded."""
        pages = [
            _make_page(1, status="ok"),
            _make_page(2, status="error"),
            _make_page(3, status="empty"),
            _make_page(4, status="ok"),
        ]
        chunks = chunk_pages(pages, chunk_size=10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 2)
        seqs = [p["sequence"] for p in chunks[0]]
        self.assertEqual(seqs, [1, 4])

    def test_filters_short_text(self):
        """Pages with text shorter than 20 chars should be excluded."""
        pages = [
            _make_page(1, text="Too short"),
            _make_page(2, text="This is a valid page with enough text to pass the filter."),
        ]
        chunks = chunk_pages(pages, chunk_size=10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 1)
        self.assertEqual(chunks[0][0]["sequence"], 2)

    def test_all_filtered_returns_empty(self):
        """If all pages are invalid, return empty list."""
        pages = [
            _make_page(1, status="error"),
            _make_page(2, text="tiny"),
        ]
        chunks = chunk_pages(pages, chunk_size=10)
        self.assertEqual(chunks, [])

    def test_empty_input(self):
        """Empty page list should return empty chunks."""
        self.assertEqual(chunk_pages([], chunk_size=5), [])


class TestAssembleChunkText(unittest.TestCase):

    def test_assembles_with_page_markers(self):
        """Assembled text should include page header markers."""
        pages = [
            _make_page(1, text="First page content", source_file="book.pdf", source_page=1),
            _make_page(2, text="Second page content", source_file="book.pdf", source_page=2),
        ]
        text = _assemble_chunk_text(pages)
        self.assertIn("--- PAGE 1: book.pdf, page 1 ---", text)
        self.assertIn("First page content", text)
        self.assertIn("--- PAGE 2: book.pdf, page 2 ---", text)
        self.assertIn("Second page content", text)


class TestRefineChunk(unittest.TestCase):

    def test_successful_refinement(self):
        """Mock successful API call and check output structure."""
        client = MagicMock()
        client.messages.create.return_value = _mock_refine_response(
            text="The house was built in 1890."
        )
        chunk = [_make_page(1, text="Thr housr was bu1lt in l890.")]
        result = refine_chunk(chunk, chunk_num=1, total_chunks=1, client=client)

        self.assertEqual(result["status"], "ok")
        self.assertIn("1890", result["refined_text"])
        self.assertEqual(result["tokens_used"], 450)

    def test_api_failure_returns_raw_fallback(self):
        """If API fails, raw text should be returned (no data loss)."""
        client = MagicMock()
        client.messages.create.side_effect = Exception("Server error")

        chunk = [_make_page(1, text="Important text that must not be lost.")]
        result = refine_chunk(chunk, chunk_num=1, total_chunks=1, client=client)

        self.assertEqual(result["status"], "fallback")
        self.assertIn("Important text that must not be lost", result["refined_text"])
        self.assertEqual(result["tokens_used"], 0)

    def test_preserves_markers(self):
        """Markers like [illegible] should appear in the assembled text sent to API."""
        client = MagicMock()
        client.messages.create.return_value = _mock_refine_response(
            text="Kept the [illegible] marker and [guess?] too."
        )
        chunk = [_make_page(1, text="Some text [illegible] and word [guess?] here.")]
        result = refine_chunk(chunk, chunk_num=1, total_chunks=1, client=client)

        self.assertEqual(result["status"], "ok")
        # Verify the raw text passed to API contains the markers
        call_args = client.messages.create.call_args
        user_msg = call_args.kwargs["messages"][0]["content"]
        self.assertIn("[illegible]", user_msg)
        self.assertIn("[guess?]", user_msg)


class TestRefineTranscript(unittest.TestCase):

    @patch("shared.refiner.time.sleep")
    def test_end_to_end_with_mock(self, mock_sleep):
        """Full pipeline: chunk → refine → reassemble."""
        client = MagicMock()
        client.messages.create.return_value = _mock_refine_response(text="Refined chunk.")

        pages = [_make_page(i) for i in range(1, 6)]
        result = refine_transcript(pages, chunk_size=3, client=client)

        self.assertIn("Refined chunk.", result["refined_text"])
        self.assertEqual(result["stats"]["chunks"], 2)  # 5 pages / 3 = 2 chunks
        self.assertEqual(result["stats"]["tokens_used"], 900)  # 450 * 2
        self.assertEqual(result["stats"]["fallback_count"], 0)

    @patch("shared.refiner.time.sleep")
    def test_mixed_success_and_failure(self, mock_sleep):
        """One chunk succeeds, one fails — stats should reflect both."""
        client = MagicMock()
        client.messages.create.side_effect = [
            _mock_refine_response(text="Good chunk."),
            Exception("API down"),
        ]

        pages = [_make_page(i) for i in range(1, 5)]
        result = refine_transcript(pages, chunk_size=2, client=client)

        self.assertEqual(result["stats"]["chunks"], 2)
        self.assertEqual(result["stats"]["fallback_count"], 1)
        # Refined text should contain both the good chunk and the raw fallback
        self.assertIn("Good chunk.", result["refined_text"])

    def test_no_valid_pages(self):
        """All pages filtered out should return empty result."""
        pages = [_make_page(1, status="error"), _make_page(2, text="short")]
        result = refine_transcript(pages)

        self.assertEqual(result["refined_text"], "")
        self.assertEqual(result["stats"]["chunks"], 0)


if __name__ == "__main__":
    unittest.main()

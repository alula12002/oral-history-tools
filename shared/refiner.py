import logging
import time

import anthropic
from tqdm import tqdm

from config import API_DELAY_SECONDS, CHUNK_SIZE_PAGES, MAX_TOKENS_REFINE, MODEL

logger = logging.getLogger("oral-history-tools")

REFINE_SYSTEM_PROMPT = """You are an expert editor cleaning up raw OCR transcriptions for an oral history and archival project.

RULES:
1. Fix obvious OCR errors (e.g., "rn" misread as "m", "l" misread as "1", etc.)
2. Restore paragraph structure and logical flow.
3. Preserve the ORIGINAL language, dialect, and voice — do NOT modernize or "correct" authentic speech patterns.
4. Keep all [illegible], [guess?], [damaged/missing], [STAMP], [SEAL] markers from the raw transcription.
5. If you spot text that was likely misread, correct it but add a footnote: [OCR corrected: original read "X"].
6. Do NOT add any content that isn't in the original document.
7. Do NOT summarize or condense — output the full text.

OUTPUT FORMAT:
Return ONLY the cleaned transcription. No preamble, no explanation."""


def chunk_pages(pages, chunk_size=None):
    """Group transcribed pages into chunks for refinement.

    Args:
        pages: List of page_entry dicts (must have "text" and "status" fields).
        chunk_size: Pages per chunk (default from config).

    Returns:
        List of chunks, where each chunk is a list of page_entry dicts.
    """
    chunk_size = chunk_size or CHUNK_SIZE_PAGES

    valid = [p for p in pages if p.get("status") == "ok" and len(p.get("text", "").strip()) >= 20]

    if not valid:
        logger.warning("No valid pages to refine (all filtered out)")
        return []

    logger.info("Chunking %d valid pages into groups of %d", len(valid), chunk_size)

    chunks = []
    for i in range(0, len(valid), chunk_size):
        chunks.append(valid[i : i + chunk_size])

    return chunks


def _assemble_chunk_text(chunk):
    """Concatenate page texts with provenance markers."""
    parts = []
    for page in chunk:
        header = (
            f"--- PAGE {page['sequence']}: "
            f"{page['source_file']}, page {page['source_page']} ---"
        )
        parts.append(f"{header}\n{page['text']}")
    return "\n\n".join(parts)


def refine_chunk(chunk, chunk_num, total_chunks, client=None):
    """Send a chunk of concatenated page text to Claude for refinement.

    Args:
        chunk: List of page_entry dicts for this chunk.
        chunk_num: 1-indexed chunk number.
        total_chunks: Total number of chunks.
        client: Optional anthropic.Anthropic client.

    Returns:
        Dict with refined_text, tokens_used, status ("ok" or "fallback").
    """
    raw_text = _assemble_chunk_text(chunk)

    if client is None:
        client = anthropic.Anthropic()

    user_msg = (
        f"Clean up this raw OCR transcription (chunk {chunk_num} of {total_chunks}).\n\n"
        f"{raw_text}"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS_REFINE,
            system=REFINE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        refined = response.content[0].text if response.content else raw_text
        tokens = response.usage.input_tokens + response.usage.output_tokens

        logger.info(
            "Chunk %d/%d refined: %d → %d chars, %d tokens",
            chunk_num, total_chunks, len(raw_text), len(refined), tokens,
        )
        return {"refined_text": refined, "tokens_used": tokens, "status": "ok"}

    except Exception as e:
        logger.error("Refinement API failed for chunk %d: %s — using raw text", chunk_num, e)
        return {"refined_text": raw_text, "tokens_used": 0, "status": "fallback"}


def refine_transcript(all_pages, chunk_size=None, client=None):
    """Chunk pages, refine each chunk, reassemble.

    Args:
        all_pages: List of page_entry dicts from transcribe_batch().
        chunk_size: Pages per chunk (default from config).
        client: Optional anthropic.Anthropic client.

    Returns:
        Dict with refined_text and stats (chunks, tokens_used, fallback_count).
    """
    chunks = chunk_pages(all_pages, chunk_size)

    if not chunks:
        return {
            "refined_text": "",
            "stats": {"chunks": 0, "tokens_used": 0, "fallback_count": 0},
        }

    if client is None:
        client = anthropic.Anthropic()

    total_chunks = len(chunks)
    refined_parts = []
    total_tokens = 0
    fallback_count = 0

    for i, chunk in enumerate(tqdm(chunks, desc="Refining", unit="chunk"), start=1):
        result = refine_chunk(chunk, i, total_chunks, client=client)
        refined_parts.append(result["refined_text"])
        total_tokens += result["tokens_used"]
        if result["status"] == "fallback":
            fallback_count += 1

        if i < total_chunks:
            time.sleep(API_DELAY_SECONDS)

    refined_text = "\n\n".join(refined_parts)

    print(f"\nRefinement complete: {total_chunks} chunks, {total_tokens:,} tokens")
    if fallback_count:
        print(f"  WARNING: {fallback_count} chunks used raw fallback text (API errors)")

    return {
        "refined_text": refined_text,
        "stats": {
            "chunks": total_chunks,
            "tokens_used": total_tokens,
            "fallback_count": fallback_count,
        },
    }

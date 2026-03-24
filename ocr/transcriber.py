import asyncio
import base64
import json
import logging
import os
import re
import time

import anthropic
from tqdm import tqdm

from config import API_DELAY_SECONDS, MAX_CONCURRENT_TRANSCRIBE, MAX_TOKENS_OCR, MODEL, RAW_DIR

logger = logging.getLogger("oral-history-tools")

OCR_SYSTEM_PROMPT = """You are an expert document transcriber for an oral history and archival project. Your task is to produce a faithful, accurate transcription of the document image(s) provided.

RULES:
1. Transcribe ALL visible text exactly as written — preserve original spelling, grammar, punctuation, and formatting.
2. For HANDWRITTEN text: Do your best to decipher every word. If a word is truly illegible, write [illegible] in its place. If you're uncertain but have a best guess, write [guess?] after the word.
3. For PRINTED text: Transcribe verbatim. Note any damage, smudges, or missing portions with [damaged/missing].
4. Preserve paragraph breaks and logical structure. Use blank lines between paragraphs.
5. If the document has headers, titles, dates, or signatures, mark them clearly:
   --- HEADER ---
   --- DATE ---
   --- SIGNATURE ---
6. If text is in a non-English language (especially Amharic or other Ethiopian languages), transcribe it in its original script AND provide a transliteration in brackets.
7. Note any stamps, seals, or non-text markings as [STAMP: description] or [SEAL: description].
8. At the end, add a confidence line: "CONFIDENCE: X%" where X is your overall confidence in the transcription accuracy.

OUTPUT FORMAT:
Return ONLY the transcribed text. No preamble, no explanation, no markdown formatting. Just the raw transcription with the notation markers described above."""

MODE_HINTS = {
    "handwritten": "This is a HANDWRITTEN document. Pay extra attention to letter formation and context clues.",
    "printed": "This is a PRINTED/TYPED document. Focus on accurate character recognition.",
    "mixed": "This document may contain BOTH handwritten and printed text. Handle each appropriately.",
}


def _checkpoint_basename(page_entry):
    """Generate checkpoint filename base from a page entry."""
    safe_name = re.sub(r"[^\w\-.]", "_", os.path.splitext(page_entry["source_file"])[0])
    return f"seq_{page_entry['sequence']:03d}__{safe_name}__page_{page_entry['source_page']}"


def transcribe_page(page_entry, total_pages, mode="handwritten", client=None):
    """Transcribe a single page image via Claude Vision API.

    Args:
        page_entry: Dict from prepare_batch (must have image_bytes, sequence, source_file, source_page).
        total_pages: Total number of pages in the batch.
        mode: "handwritten", "printed", or "mixed".
        client: Optional anthropic.Anthropic client (created if not provided).

    Returns:
        Enriched page_entry dict with text, confidence, tokens_used, status, error_message.
    """
    result = {
        **{k: v for k, v in page_entry.items() if k != "image_bytes"},
        "text": "",
        "confidence": None,
        "tokens_used": 0,
        "status": "error",
        "error_message": None,
    }

    if client is None:
        client = anthropic.Anthropic()

    mode_hint = MODE_HINTS.get(mode, MODE_HINTS["handwritten"])
    b64 = base64.b64encode(page_entry["image_bytes"]).decode("utf-8")

    user_text = (
        f"{mode_hint}\n\n"
        f"Transcribe this document page. "
        f"Page {page_entry['sequence']} of {total_pages}. "
        f"Source: {page_entry['source_file']}, page {page_entry['source_page']}."
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS_OCR,
            system=OCR_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }],
        )
    except Exception as e:
        logger.error("API error on page %d: %s", page_entry["sequence"], e)
        result["error_message"] = str(e)
        return result

    text = response.content[0].text if response.content else ""
    tokens = response.usage.input_tokens + response.usage.output_tokens

    # Parse confidence
    confidence = None
    match = re.search(r"CONFIDENCE:\s*(\d+)%", text)
    if match:
        confidence = match.group(1) + "%"

    if not text or len(text.strip()) < 5:
        result.update(text=text, confidence=confidence, tokens_used=tokens, status="empty")
    else:
        result.update(text=text, confidence=confidence, tokens_used=tokens, status="ok")

    logger.info(
        "Page %d/%d transcribed: %d chars, confidence=%s, tokens=%d",
        page_entry["sequence"], total_pages, len(text), confidence, tokens,
    )
    return result


async def transcribe_page_async(page_entry, total_pages, mode="handwritten",
                                client=None, semaphore=None):
    """Transcribe a single page via Claude Vision API with concurrency control and retry.

    Args:
        page_entry: Dict from prepare_batch.
        total_pages: Total number of pages in the batch.
        mode: "handwritten", "printed", or "mixed".
        client: anthropic.AsyncAnthropic client.
        semaphore: asyncio.Semaphore for concurrency limiting.

    Returns:
        Enriched page_entry dict (same structure as transcribe_page).
    """
    result = {
        **{k: v for k, v in page_entry.items() if k != "image_bytes"},
        "text": "",
        "confidence": None,
        "tokens_used": 0,
        "status": "error",
        "error_message": None,
    }

    mode_hint = MODE_HINTS.get(mode, MODE_HINTS["handwritten"])
    b64 = base64.b64encode(page_entry["image_bytes"]).decode("utf-8")

    user_text = (
        f"{mode_hint}\n\n"
        f"Transcribe this document page. "
        f"Page {page_entry['sequence']} of {total_pages}. "
        f"Source: {page_entry['source_file']}, page {page_entry['source_page']}."
    )

    max_retries = 3

    async with semaphore:
        for attempt in range(max_retries + 1):
            try:
                response = await client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS_OCR,
                    system=OCR_SYSTEM_PROMPT,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": b64,
                                },
                            },
                            {"type": "text", "text": user_text},
                        ],
                    }],
                )
                break
            except (anthropic.RateLimitError, anthropic.APIStatusError,
                    anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
                # Retry on transient errors: rate limits, 500/529, connection, timeout
                is_permanent = (
                    isinstance(e, anthropic.APIStatusError)
                    and e.status_code not in (429, 500, 502, 503, 529)
                )
                if is_permanent:
                    logger.error("Non-retryable API error on page %d: %s", page_entry["sequence"], e)
                    result["error_message"] = str(e)
                    return result
                if attempt < max_retries:
                    delay = min(2 ** attempt * 2, 60)
                    logger.warning(
                        "Transient error on page %d (%s), backing off %ds (attempt %d/%d)",
                        page_entry["sequence"], type(e).__name__, delay, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("Retries exhausted for page %d after %d attempts: %s",
                                 page_entry["sequence"], max_retries, e)
                    result["error_message"] = f"Failed after {max_retries} retries: {e}"
                    return result
            except Exception as e:
                logger.error("Unexpected error on page %d: %s", page_entry["sequence"], e)
                result["error_message"] = str(e)
                return result

    text = response.content[0].text if response.content else ""
    tokens = response.usage.input_tokens + response.usage.output_tokens

    confidence = None
    match = re.search(r"CONFIDENCE:\s*(\d+)%", text)
    if match:
        confidence = match.group(1) + "%"

    if not text or len(text.strip()) < 5:
        result.update(text=text, confidence=confidence, tokens_used=tokens, status="empty")
    else:
        result.update(text=text, confidence=confidence, tokens_used=tokens, status="ok")

    logger.info(
        "Page %d/%d transcribed: %d chars, confidence=%s, tokens=%d",
        page_entry["sequence"], total_pages, len(text), confidence, tokens,
    )
    return result


async def transcribe_batch_concurrent(prepared_pages, mode="handwritten",
                                      max_concurrent=None, progress_callback=None):
    """Transcribe pages concurrently with rate-limit handling.

    Args:
        prepared_pages: List of page dicts from prepare_batch().
        mode: "handwritten", "printed", or "mixed".
        max_concurrent: Max concurrent API calls (default from config).
        progress_callback: Optional callable(completed_count, total_pages, result)
            called after each page completes.

    Returns:
        List of enriched page_entry dicts in original order.
    """
    max_concurrent = max_concurrent or MAX_CONCURRENT_TRANSCRIBE
    client = anthropic.AsyncAnthropic()
    semaphore = asyncio.Semaphore(max_concurrent)
    total_pages = len(prepared_pages)

    logger.info(
        "Starting concurrent transcription: %d pages, max_concurrent=%d",
        total_pages, max_concurrent,
    )
    t0 = time.monotonic()

    results = [None] * total_pages
    completed_count = 0
    lock = asyncio.Lock()

    async def process_page(index, page):
        nonlocal completed_count
        result = await transcribe_page_async(page, total_pages, mode, client, semaphore)
        async with lock:
            results[index] = result
            completed_count += 1
            if progress_callback:
                progress_callback(completed_count, total_pages, result)
        return result

    tasks = [process_page(i, page) for i, page in enumerate(prepared_pages)]
    await asyncio.gather(*tasks)

    elapsed = time.monotonic() - t0
    ok_count = sum(1 for r in results if r and r.get("status") == "ok")
    total_tokens = sum(r.get("tokens_used", 0) for r in results if r)
    logger.info(
        "Concurrent transcription done: %d/%d ok in %.1fs, %d tokens",
        ok_count, total_pages, elapsed, total_tokens,
    )

    return results


def _save_checkpoint(result, output_dir):
    """Save a page result as .txt and .json checkpoint files."""
    basename = _checkpoint_basename(result)
    txt_path = os.path.join(output_dir, basename + ".txt")
    json_path = os.path.join(output_dir, basename + ".json")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(result.get("text", ""))

    # Save everything except image_bytes
    meta = {k: v for k, v in result.items() if k != "image_bytes"}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)

    logger.debug("Checkpoint saved: %s", basename)


def _find_completed_sequences(output_dir):
    """Scan output_dir for existing checkpoint .json files, return set of completed sequence numbers."""
    completed = set()
    if not os.path.isdir(output_dir):
        return completed
    for name in os.listdir(output_dir):
        if name.endswith(".json") and name.startswith("seq_"):
            try:
                json_path = os.path.join(output_dir, name)
                with open(json_path) as f:
                    data = json.load(f)
                if data.get("status") == "ok":
                    completed.add(data["sequence"])
            except (json.JSONDecodeError, KeyError):
                continue
    return completed


def transcribe_batch(prepared_pages, mode="handwritten", output_dir=None):
    """Transcribe all pages in a batch with checkpointing and resume.

    Args:
        prepared_pages: List of page dicts from prepare_batch().
        mode: "handwritten", "printed", or "mixed".
        output_dir: Directory for checkpoints (default: RAW_DIR).

    Returns:
        List of enriched page_entry dicts.
    """
    output_dir = output_dir or RAW_DIR
    os.makedirs(output_dir, exist_ok=True)

    # Check for existing checkpoints to resume
    completed = _find_completed_sequences(output_dir)
    if completed:
        logger.info("Resuming: found %d already-completed pages", len(completed))

    client = anthropic.Anthropic()
    total_pages = len(prepared_pages)
    results = []
    succeeded = 0
    failed = 0
    empty = 0
    total_tokens = 0

    for page in tqdm(prepared_pages, desc="Transcribing", unit="page"):
        if page["sequence"] in completed:
            logger.info("Skipping page %d (already checkpointed)", page["sequence"])
            # Load existing result from checkpoint
            basename = _checkpoint_basename(page)
            json_path = os.path.join(output_dir, basename + ".json")
            with open(json_path) as f:
                cached = json.load(f)
            results.append(cached)
            succeeded += 1
            total_tokens += cached.get("tokens_used", 0)
            continue

        result = transcribe_page(page, total_pages, mode=mode, client=client)

        if result["status"] == "ok":
            succeeded += 1
            _save_checkpoint(result, output_dir)
        elif result["status"] == "empty":
            empty += 1
            _save_checkpoint(result, output_dir)
        else:
            failed += 1

        total_tokens += result["tokens_used"]
        results.append(result)

        # Rate limit delay between API calls
        if page["sequence"] < total_pages:
            time.sleep(API_DELAY_SECONDS)

    print(f"\nTranscription complete: {succeeded} succeeded, {failed} failed, {empty} empty")
    print(f"Total tokens used: {total_tokens:,}")

    return results

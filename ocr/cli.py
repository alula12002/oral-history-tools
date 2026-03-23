#!/usr/bin/env python3
"""CLI entry point for the OCR document transcription pipeline.

Usage:
    python -m ocr.cli [OPTIONS]

Examples:
    python -m ocr.cli                          # defaults: handwritten mode, sort by modified
    python -m ocr.cli --mode printed           # printed document mode
    python -m ocr.cli --sort name              # process files alphabetically
    python -m ocr.cli --skip-refine            # raw OCR only, no refinement pass
    python -m ocr.cli --resume                 # resume from last checkpoint
    python -m ocr.cli --title "Family History" # set document title for .docx export
"""

import argparse
import sys
import time

from shared.utils import setup_logging, ensure_dirs, load_env
from config import INPUT_DIR, RAW_DIR, REFINED_DIR


def parse_args():
    parser = argparse.ArgumentParser(
        description="Transcribe scanned documents using Claude Vision API"
    )
    parser.add_argument(
        "--mode",
        choices=["handwritten", "printed", "mixed"],
        default="handwritten",
        help="Document type hint for OCR (default: handwritten)",
    )
    parser.add_argument(
        "--sort",
        choices=["modified", "name", "manual"],
        default="modified",
        help="File processing order (default: modified time)",
    )
    parser.add_argument(
        "--skip-refine",
        action="store_true",
        help="Skip the refinement pass, export raw OCR only",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing checkpoints in output/raw/",
    )
    parser.add_argument(
        "--title",
        default="Document Transcription",
        help="Title for the .docx export (default: 'Document Transcription')",
    )
    parser.add_argument(
        "--input-dir",
        default=INPUT_DIR,
        help=f"Input directory (default: {INPUT_DIR})",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="DPI for PDF rasterization (default: 200)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # --- Setup ---
    setup_logging()
    ensure_dirs()

    try:
        load_env()
    except ValueError as e:
        print(f"\nERROR: {e}")
        print("Set your API key in .env before running.")
        sys.exit(1)

    # --- Phase 2: Scan & compress ---
    from ocr.scanner import prepare_batch

    print(f"\n{'='*60}")
    print(f"  OCR Document Transcription Pipeline")
    print(f"  Mode: {args.mode} | Sort: {args.sort} | DPI: {args.dpi}")
    print(f"{'='*60}\n")

    start = time.time()

    print("Scanning input files...")
    batch = prepare_batch(args.input_dir, sort_by=args.sort)

    if not batch:
        print(f"\nNo supported files found in {args.input_dir}/")
        print("Drop .jpg, .png, .pdf, .tiff, or .bmp files there and re-run.")
        sys.exit(0)

    # --- Phase 3: Transcribe ---
    from ocr.transcriber import transcribe_batch

    print(f"\nTranscribing {len(batch)} pages via Claude Vision API...")
    results = transcribe_batch(batch, mode=args.mode, output_dir=RAW_DIR)

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    if ok_count == 0:
        print("\nERROR: No pages were successfully transcribed. Check API key and network.")
        sys.exit(1)

    # --- Phase 4: Refine (optional) ---
    if args.skip_refine:
        print("\nSkipping refinement (--skip-refine).")
        # Assemble raw text with page markers
        parts = []
        for r in results:
            if r.get("status") == "ok":
                header = f"--- PAGE {r['sequence']}: {r['source_file']}, page {r['source_page']} ---"
                parts.append(f"{header}\n{r['text']}")
        final_text = "\n\n".join(parts)
        refine_tokens = 0
    else:
        from shared.refiner import refine_transcript

        print(f"\nRefining transcript ({ok_count} pages)...")
        refine_result = refine_transcript(results)
        final_text = refine_result["refined_text"]
        refine_tokens = refine_result["stats"]["tokens_used"]

    # --- Phase 5: Export ---
    from shared.exporter import export_all

    # Gather metadata for title page
    source_files = len(set(r["source_file"] for r in results))
    ocr_tokens = sum(r.get("tokens_used", 0) for r in results)
    metadata = {
        "pages": ok_count,
        "source_files": source_files,
        "tokens_used": ocr_tokens + refine_tokens,
    }

    export_all(
        final_text,
        output_dir=REFINED_DIR,
        title=args.title,
        metadata=metadata,
    )

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s.")
    print(f"  OCR tokens:    {ocr_tokens:,}")
    if not args.skip_refine:
        print(f"  Refine tokens: {refine_tokens:,}")
    print(f"  Total tokens:  {ocr_tokens + refine_tokens:,}")


if __name__ == "__main__":
    main()

import io
import logging
import os
from datetime import datetime

from PIL import Image, ImageOps
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFPageCountError

from config import (
    INPUT_DIR,
    JPEG_MIN_QUALITY,
    JPEG_QUALITY,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIM,
)

logger = logging.getLogger("oral-history-tools")

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
SUPPORTED_PDF_EXTS = {".pdf"}
SUPPORTED_EXTS = SUPPORTED_IMAGE_EXTS | SUPPORTED_PDF_EXTS


def discover_files(input_dir=INPUT_DIR, sort_by="modified"):
    """Find all supported image/PDF files in input_dir.

    Args:
        input_dir: Directory to scan.
        sort_by: "modified" (default), "name", or "manual" (reads input/order.txt).

    Returns:
        List of dicts with filepath, type, size, modified.
    """
    entries = []
    for name in os.listdir(input_dir):
        if name.startswith("."):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUPPORTED_EXTS:
            continue
        path = os.path.join(input_dir, name)
        if not os.path.isfile(path):
            continue
        stat = os.stat(path)
        entries.append({
            "filepath": path,
            "type": "pdf" if ext in SUPPORTED_PDF_EXTS else "image",
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime),
        })

    if sort_by == "name":
        entries.sort(key=lambda e: os.path.basename(e["filepath"]).lower())
    elif sort_by == "manual":
        order_file = os.path.join(input_dir, "order.txt")
        if os.path.exists(order_file):
            with open(order_file) as f:
                order = [line.strip() for line in f if line.strip()]
            order_map = {name: i for i, name in enumerate(order)}
            entries.sort(
                key=lambda e: order_map.get(os.path.basename(e["filepath"]), 999999)
            )
        else:
            logger.warning("sort_by='manual' but %s not found, using modified time", order_file)
            entries.sort(key=lambda e: e["modified"])
    else:  # modified
        entries.sort(key=lambda e: e["modified"])

    logger.info("Discovered %d files in %s (sort: %s)", len(entries), input_dir, sort_by)
    return entries


def compress_image(image_or_path, max_dim=None, quality=None, max_bytes=None):
    """Compress an image to JPEG under the API size limit.

    Args:
        image_or_path: File path (str) or PIL Image object.
        max_dim: Max pixels on longest side (default from config).
        quality: Starting JPEG quality (default from config).
        max_bytes: Max output size in bytes (default from config).

    Returns:
        JPEG bytes.
    """
    max_dim = max_dim or MAX_IMAGE_DIM
    quality = quality or JPEG_QUALITY
    max_bytes = max_bytes or MAX_IMAGE_BYTES

    if isinstance(image_or_path, str):
        img = Image.open(image_or_path)
        original_bytes = os.path.getsize(image_or_path)
    else:
        img = image_or_path
        # Estimate original size from raw pixel data
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        original_bytes = buf.tell()

    original_dims = img.size

    # Auto-orient using EXIF (critical for iPhone photos)
    img = ImageOps.exif_transpose(img)

    # Convert to RGB if needed (RGBA, palette, etc.)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Resize to fit within max_dim on longest side
    w, h = img.size
    longest = max(w, h)
    if longest > max_dim:
        scale = max_dim / longest
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    resized_dims = img.size

    # Compress with progressive quality reduction
    attempts = 0
    max_attempts = 5
    current_quality = quality

    while attempts < max_attempts:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=current_quality, optimize=True)
        compressed_bytes = buf.tell()

        if compressed_bytes <= max_bytes:
            break

        attempts += 1
        current_quality = max(current_quality - 10, JPEG_MIN_QUALITY)
        if current_quality <= JPEG_MIN_QUALITY and attempts > 1:
            logger.warning(
                "Image still %d bytes after %d attempts at quality %d",
                compressed_bytes, attempts, current_quality,
            )
            break

    final_bytes = buf.tell()
    logger.info(
        "Compressed: %dx%d → %dx%d, %s → %s, quality=%d",
        original_dims[0], original_dims[1],
        resized_dims[0], resized_dims[1],
        _fmt_bytes(original_bytes), _fmt_bytes(final_bytes),
        current_quality,
    )

    return buf.getvalue()


def extract_pdf_pages(filepath, dpi=200):
    """Extract each page of a PDF as a compressed JPEG.

    Args:
        filepath: Path to PDF file.
        dpi: Resolution for rasterization (default 200).

    Returns:
        List of dicts with pdf_source, pdf_page, image_bytes, compressed_size.
    """
    filename = os.path.basename(filepath)
    logger.info("Extracting pages from PDF: %s (dpi=%d)", filename, dpi)

    try:
        pages = convert_from_path(filepath, dpi=dpi)
    except PDFPageCountError:
        logger.error("Failed to read PDF: %s (corrupt or empty?)", filename)
        return []
    except Exception as e:
        logger.error("PDF extraction failed for %s: %s", filename, e)
        return []

    results = []
    for i, page_img in enumerate(pages, start=1):
        logger.info("  Processing page %d/%d of %s", i, len(pages), filename)
        image_bytes = compress_image(page_img)
        results.append({
            "pdf_source": filename,
            "pdf_page": i,
            "image_bytes": image_bytes,
            "compressed_size": len(image_bytes),
        })

    logger.info("Extracted %d pages from %s", len(results), filename)
    return results


def prepare_batch(input_dir=INPUT_DIR, sort_by="modified"):
    """Discover files, compress images, extract PDFs, assign sequence numbers.

    Returns:
        List of page dicts with sequence, source_file, source_page, source_type,
        image_bytes, original_size, compressed_size.
    """
    files = discover_files(input_dir, sort_by)
    if not files:
        logger.info("No files found in %s", input_dir)
        return []

    batch = []
    sequence = 0

    # Track per-file stats for summary
    file_stats = []

    for entry in files:
        filepath = entry["filepath"]
        filename = os.path.basename(filepath)
        file_original_total = entry["size"]

        if entry["type"] == "pdf":
            pages = extract_pdf_pages(filepath)
            file_compressed_total = sum(p["compressed_size"] for p in pages)
            file_stats.append({
                "name": filename,
                "pages": len(pages),
                "original": file_original_total,
                "compressed": file_compressed_total,
            })
            for page in pages:
                sequence += 1
                batch.append({
                    "sequence": sequence,
                    "source_file": filename,
                    "source_page": page["pdf_page"],
                    "source_type": "pdf",
                    "image_bytes": page["image_bytes"],
                    "original_size": file_original_total,
                    "compressed_size": page["compressed_size"],
                })
        else:
            sequence += 1
            image_bytes = compress_image(filepath)
            compressed_size = len(image_bytes)
            file_stats.append({
                "name": filename,
                "pages": 1,
                "original": file_original_total,
                "compressed": compressed_size,
            })
            batch.append({
                "sequence": sequence,
                "source_file": filename,
                "source_page": 1,
                "source_type": "image",
                "image_bytes": image_bytes,
                "original_size": file_original_total,
                "compressed_size": compressed_size,
            })

    # Print summary
    _print_summary(file_stats, batch)

    return batch


def _print_summary(file_stats, batch):
    """Print a formatted summary table of the batch."""
    total_pages = sum(f["pages"] for f in file_stats)
    total_original = sum(f["original"] for f in file_stats)
    total_compressed = sum(f["compressed"] for f in file_stats)

    print(f"\nFound {len(file_stats)} files → {total_pages} total pages:")
    for f in file_stats:
        page_word = "page" if f["pages"] == 1 else "pages"
        print(
            f"  {f['name']:<40} {f['pages']:>3} {page_word}   "
            f"({_fmt_bytes(f['original'])} → {_fmt_bytes(f['compressed'])})"
        )

    all_under = all(p["compressed_size"] <= MAX_IMAGE_BYTES for p in batch)
    check = "✓" if all_under else "✗ WARNING: some pages exceed limit!"
    print(f"\nTotal: {total_pages} pages, {_fmt_bytes(total_original)} → {_fmt_bytes(total_compressed)} compressed")
    print(f"All pages under {_fmt_bytes(MAX_IMAGE_BYTES)} limit: {check}")


def _fmt_bytes(n):
    """Format byte count as human-readable string."""
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    else:
        return f"{n / (1024 * 1024):.1f} MB"

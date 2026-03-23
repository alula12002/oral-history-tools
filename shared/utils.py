import logging
import os
import sys

from dotenv import load_dotenv

from config import INPUT_DIR, RAW_DIR, REFINED_DIR, OUTPUT_DIR

logger = logging.getLogger("oral-history-tools")


def setup_logging():
    """Configure logger with timestamps to console and output/processing.log."""
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_handler = logging.FileHandler(os.path.join(OUTPUT_DIR, "processing.log"))
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info("Logging initialized")


def ensure_dirs():
    """Create input/, output/raw/, output/refined/ if they don't exist."""
    for d in [INPUT_DIR, RAW_DIR, REFINED_DIR]:
        os.makedirs(d, exist_ok=True)
        logger.debug("Ensured directory: %s", d)


def load_env():
    """Load .env and validate ANTHROPIC_API_KEY is set and not placeholder."""
    load_dotenv()
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or key == "your-key-here":
        logger.error("ANTHROPIC_API_KEY is missing or still set to placeholder")
        raise ValueError(
            "Set ANTHROPIC_API_KEY in .env to a valid API key"
        )
    logger.info("API key loaded (ends with ...%s)", key[-4:])
    return key

from __future__ import annotations

import logging


def configure_logging(level: str, debug_logging: bool) -> logging.Logger:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [voice-pipeline] %(message)s",
    )
    logger = logging.getLogger("voice_pipeline")
    if debug_logging:
        logger.setLevel(logging.DEBUG)
    return logger

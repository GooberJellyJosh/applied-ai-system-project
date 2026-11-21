"""
Logging setup for the VibeFinder assistant.

Every request, retrieval result, plan, self-check, and error is written to
logs/vibefinder.log so a run can be reviewed afterwards. Errors are also
shown in the terminal.
"""

import logging
import sys
from pathlib import Path

LOGGER_NAME = "vibefinder"
DEFAULT_LOG_DIR = "logs"
LOG_FILE_NAME = "vibefinder.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def configure_logging(log_dir: str = DEFAULT_LOG_DIR, show_info_in_terminal: bool = False) -> logging.Logger:
    """
    Set up the shared "vibefinder" logger and return it.

    Calling this more than once is safe: existing handlers are replaced, so
    log lines are never duplicated.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # keep log lines out of the root logger

    # Remove handlers from an earlier call before adding fresh ones
    for existing_handler in list(logger.handlers):
        logger.removeHandler(existing_handler)
        existing_handler.close()

    formatter = logging.Formatter(LOG_FORMAT)

    # Terminal handler: errors only, so normal output stays readable. Handled
    # situations such as a rejected request are warnings and go to the file.
    terminal_handler = logging.StreamHandler(sys.stderr)
    terminal_handler.setLevel(logging.INFO if show_info_in_terminal else logging.ERROR)
    terminal_handler.setFormatter(formatter)
    logger.addHandler(terminal_handler)

    # File handler: the full record of the run. If the log folder cannot be
    # created (for example on a read-only disk) the app keeps working and
    # only logs to the terminal.
    try:
        log_directory = Path(log_dir)
        log_directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_directory / LOG_FILE_NAME, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as error:
        logger.warning("Could not open the log file in '%s': %s", log_dir, error)

    return logger


def get_logger(component_name: str) -> logging.Logger:
    """Return a child logger such as "vibefinder.retriever" for one component."""
    return logging.getLogger(f"{LOGGER_NAME}.{component_name}")

"""
error_handler.py
Centralized logging and exception handling for the AI Surveillance System.

Usage:
    from error_handler import logger, safe_run

    logger.info("Camera started")
    logger.warning("Face not matched")

    @safe_run
    def detect_faces(frame):
        ...
"""

import logging
import functools
import traceback
import sys
import os

# ---------------------------------------------------------
# Logger setup
# ---------------------------------------------------------
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("surveillance")
logger.setLevel(logging.DEBUG)

# Avoid duplicate handlers if this module gets imported more than once
if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler — shows INFO and above while running
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # File handler — captures everything, for later review / report screenshots
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


# ---------------------------------------------------------
# Exception helper — logs which file + line the error came from
# ---------------------------------------------------------
def log_exception(exc: Exception, context: str = ""):
    """
    Logs an exception with the exact file name and line number
    where it occurred, plus a short context label if given.
    """
    tb = traceback.extract_tb(exc.__traceback__)
    if tb:
        last_frame = tb[-1]  # deepest frame = where the error actually happened
        file_name = os.path.basename(last_frame.filename)
        line_no = last_frame.lineno
        func_name = last_frame.name
        logger.error(
            f"{context + ' | ' if context else ''}"
            f"{type(exc).__name__}: {exc} "
            f"[{file_name}:{line_no} in {func_name}()]"
        )
    else:
        logger.error(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------
# Decorator — wrap any function to auto-catch and log errors
# ---------------------------------------------------------
def safe_run(func):
    """
    Decorator: catches any exception in the wrapped function,
    logs file/line/context, and returns None instead of crashing
    the whole program (useful inside the live camera loop).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (KeyboardInterrupt, SystemExit):
            # Never swallow interrupts/quit signals — let them propagate
            # so 'q' / Ctrl+C reliably stop the program.
            raise
        except Exception as e:
            log_exception(e, context=f"Error in {func.__name__}()")
            return None
    return wrapper


# ---------------------------------------------------------
# Context manager — for wrapping a block of code instead of a whole function
# ---------------------------------------------------------
class error_context:
    """
    Usage:
        with error_context("Loading DNN model"):
            net = cv2.dnn.readNetFromCaffe(...)
    """
    def __init__(self, context: str = ""):
        self.context = context

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is None:
            return False

        # Never swallow KeyboardInterrupt (Ctrl+C) or SystemExit — these
        # are not bugs, they're the user/OS asking the program to stop.
        # Suppressing them would make quitting the program unreliable.
        if isinstance(exc_val, (KeyboardInterrupt, SystemExit)):
            return False

        log_exception(exc_val, context=self.context)
        return True  # suppress genuine errors so the program keeps running
# services/api/app/logging.py
import json
import logging
import sys
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """
    Formats log records as a JSON object.
    Includes timestamp, level, and message.
    """
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno
        }

        # Add exception info if present
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        # Add extra fields (e.g., user_id, trace_id) passed via 'extra' dict
        if hasattr(record, "request_id"):
            log_record["request_id"] = record.request_id

        return json.dumps(log_record)

def setup_logging():
    """
    Configures the root logger to output JSON to stdout.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove default handlers to avoid duplicate logs
    if root_logger.handlers:
        root_logger.handlers = []

    root_logger.addHandler(handler)

    # Silence noisy libraries
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)

# Initialize on import
setup_logging()

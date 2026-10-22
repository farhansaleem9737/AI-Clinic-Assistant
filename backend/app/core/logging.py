"""Structured (JSON-lines) logging built on the standard library.

Every record carries the current request id, so all lines produced while
handling one request can be correlated.

Never pass passwords, tokens, secrets or patient data to a logger: log ids and
event names, not values.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed via ``extra=``.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS:
                entry[key] = value
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Uvicorn's access log prints full URLs including query strings, which will
    # carry search terms such as patient names. The request middleware logs
    # method, path, status and duration instead.
    logging.getLogger("uvicorn.access").disabled = True
    # SQL statement logging is controlled by the SQL_ECHO setting, not LOG_LEVEL.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # boto3/botocore debug logs include signed request details. Warnings and
    # errors still come through; our own storage module logs ids and codes only.
    for name in ("boto3","botocore","urllib3","s3transfer"):
        logging.getLogger(name).setLevel(logging.WARNING)

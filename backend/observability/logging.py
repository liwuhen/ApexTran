"""Logging setup — production-grade loguru configuration.

A single, idempotent ``setup_logging()`` configures loguru with a human console
sink plus a rotating (optionally JSON) file sink, routes the stdlib ``logging``
of third-party libraries into loguru, redacts obvious secrets, and wires the
optional logfire APM. Tune it via ``ApexTran_LOG_*`` env vars (see docs/logging.md).

Application diagnostics go through loguru; business/audit events stay on the tape.
"""

from __future__ import annotations

import contextlib
import inspect
import logging
import os
import re
import sys
from pathlib import Path

_CONFIGURED = False
_CONSOLE_SINK_ID: int | None = None
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{6})[A-Za-z0-9_\-]+")


class InterceptHandler(logging.Handler):
    """Route standard-library ``logging`` records into loguru (unified sinks)."""

    def emit(self, record: logging.LogRecord) -> None:
        from loguru import logger

        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk back to the frame that issued the log, for correct name/line.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _redact(record) -> bool:
    record["message"] = _SECRET_RE.sub(r"\1…", record["message"])
    return True


def setup_logging(*, force: bool = False) -> None:
    """Configure loguru (console + rotating file [+ JSON]) and capture stdlib logging.

    Idempotent: safe to call multiple times (e.g. CLI entrypoint and library use).
    With no ``ApexTran_LOG_*`` overrides the console behaves as before, plus a
    ``~/.ApexTran/logs/ApexTran.log`` file sink is added.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    from loguru import logger

    from backend.agent.settings import load_settings

    settings = load_settings()
    env = os.getenv
    console_level = (env("ApexTran_LOG_LEVEL") or {0: "WARNING", 1: "INFO"}.get(settings.verbose, "DEBUG")).upper()
    file_level = env("ApexTran_LOG_FILE_LEVEL", "DEBUG").upper()
    log_dir = Path(env("ApexTran_LOG_DIR", str(settings.home / "logs"))).expanduser()
    as_json = env("ApexTran_LOG_JSON", "0") == "1"
    diagnose = env("ApexTran_LOG_DIAGNOSE", "0") == "1"  # off in prod: keeps variable values/secrets out of tracebacks

    logger.remove()
    logger.configure(extra={"run_id": "-", "session_id": "-", "channel": "-"})

    # Console — human-readable, colored. Tracked so the full-screen CLI TUI can
    # turn it off (logs would otherwise corrupt the prompt_toolkit UI).
    global _CONSOLE_SINK_ID
    _CONSOLE_SINK_ID = logger.add(
        sys.stderr,
        level=console_level,
        backtrace=False,
        diagnose=diagnose,
        filter=_redact,
        format=(
            "<green>{time:HH:mm:ss}</green> <level>{level: <7}</level> "
            "<cyan>{extra[run_id]}</cyan> <dim>{name}:{line}</dim> {message}"
        ),
    )

    # File — rotation / retention / compression; enqueue keeps long-running
    # services non-blocking and multiprocess-safe.
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "ApexTran.log",
        level=file_level,
        rotation=env("ApexTran_LOG_ROTATION", "20 MB"),
        retention=env("ApexTran_LOG_RETENTION", "14 days"),
        compression="zip",
        enqueue=True,
        backtrace=True,
        diagnose=diagnose,
        filter=_redact,
        serialize=as_json,  # JSON lines for Loki / ELK ingestion (carries extra fields automatically)
        # Plain-text format keeps the correlation fields (ignored when serialize=True).
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | "
            "run={extra[run_id]} session={extra[session_id]} channel={extra[channel]} | "
            "{name}:{function}:{line} - {message}"
        ),
    )

    # Capture third-party stdlib logging (langchain / httpx / telegram / sqlalchemy …).
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Optional APM. Logfire must never block local/dev startup if the user
    # hasn't authenticated or the service is unavailable.
    try:
        import logfire
    except ImportError:
        pass
    else:
        try:
            logfire.configure()
            logger.add(**logfire.loguru_handler())  # add alongside console+file (don't replace them)
        except Exception as exc:
            logger.warning("logfire disabled: {}", exc)

    _CONFIGURED = True


def disable_console_logging() -> None:
    """Remove the stderr console sink, keeping file logging.

    Call this before launching the full-screen CLI TUI so log lines don't
    corrupt the prompt_toolkit interface. Idempotent.
    """
    global _CONSOLE_SINK_ID
    if _CONSOLE_SINK_ID is None:
        return
    from loguru import logger

    with contextlib.suppress(ValueError):
        logger.remove(_CONSOLE_SINK_ID)
    _CONSOLE_SINK_ID = None


__all__ = ["InterceptHandler", "disable_console_logging", "setup_logging"]

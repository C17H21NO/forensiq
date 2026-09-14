import logging

from app.config import settings


def configure_logging() -> None:
    """
    Logging general de ForensiQ.

    No registra contenido documental,
    contraseñas, tokens ni PII.
    """

    numeric_level = getattr(
        logging,
        settings.log_level,
        logging.INFO,
    )

    logging.basicConfig(
        level=numeric_level,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
    )


def get_logger(
    name: str,
) -> logging.Logger:
    return logging.getLogger(
        name
    )
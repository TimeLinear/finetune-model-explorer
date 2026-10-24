"""오류 기록. 상세 오류(추적 정보)는 logs/app.log 에만 남기고 화면에는 짧은 안내만 보인다 (NF2004)."""
import logging

from common.config import LOG_DIR


def get_logger(name="app"):
    logger = logging.getLogger(name)
    if not logger.handlers:
        LOG_DIR.mkdir(exist_ok=True)
        handler = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger

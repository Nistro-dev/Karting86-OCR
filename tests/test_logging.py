"""Journal : rotation par taille en plus de la rotation quotidienne."""
import glob
import logging
import os

from apex_ocr.logging_setup import DailyOrSizeHandler


def test_size_rollover_archives_and_keeps_only_n_archives(tmp_path):
    path = str(tmp_path / "apex_ocr.log")
    handler = DailyOrSizeHandler(path, when="midnight", backupCount=3, encoding="utf-8",
                                 max_bytes=400, size_archives=2)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("test_rollover")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for i in range(60):
        logger.info("ligne %03d " + "x" * 40, i)
    handler.close()

    assert os.path.getsize(path) < 400
    archives = glob.glob(path + ".????-??-??_??????")
    assert 1 <= len(archives) <= 2          # au plus size_archives archives « par taille »

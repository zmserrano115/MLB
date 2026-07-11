import logging
from threading import Thread


LOGGER = logging.getLogger(__name__)


def log_background_exception(task_name):
    LOGGER.exception("Background task failed: %s", task_name)


def start_daemon_thread(name, target):
    thread = Thread(name=name, target=target, daemon=True)
    thread.start()
    return thread

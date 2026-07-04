import time
import traceback


def log_debug(area: str, message: str) -> None:
    now = time.strftime("%H:%M:%S")
    print(f"[{now}][{area}] {message}", flush=True)


def log_exception(area: str, message: str) -> None:
    log_debug(area, message)
    traceback.print_exc()


class Timer:
    def __init__(self, area: str, message: str):
        self.area = area
        self.message = message
        self.started_at = 0.0

    def __enter__(self):
        self.started_at = time.perf_counter()
        log_debug(self.area, f"START {self.message}")
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed_ms = (time.perf_counter() - self.started_at) * 1000
        status = "ERROR" if exc_type else "END"
        log_debug(self.area, f"{status} {self.message} ({elapsed_ms:.0f} ms)")
        return False

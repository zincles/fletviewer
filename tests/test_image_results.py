import threading
import time
import unittest

from app.image_results import ImageResultPump


class _Page:
    def __init__(self) -> None:
        self.updated = 0
        self.threads: list[threading.Thread] = []

    def run_thread(self, worker) -> None:
        thread = threading.Thread(target=worker, daemon=True)
        self.threads.append(thread)
        thread.start()

    def update(self) -> None:
        self.updated += 1


class ImageResultPumpTests(unittest.TestCase):
    def test_many_results_share_workers_and_batch_updates(self) -> None:
        page = _Page()
        pump = ImageResultPump(page, batch_size=3)
        applied: list[int] = []

        for index in range(10):
            pump.enqueue(lambda value=index: (applied.append(value), True)[1])

        deadline = time.monotonic() + 1
        while len(applied) < 10 and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(sorted(applied), list(range(10)))
        self.assertLessEqual(page.updated, 4)
        self.assertLessEqual(len(page.threads), 2)

    def test_navigation_priority_delays_image_updates(self) -> None:
        page = _Page()
        pump = ImageResultPump(page, batch_size=3)
        applied = threading.Event()
        pump.prioritize_navigation(0.08)

        pump.enqueue(lambda: (applied.set(), True)[1])

        self.assertFalse(applied.wait(timeout=0.03))
        self.assertTrue(applied.wait(timeout=0.3))
        self.assertEqual(page.updated, 1)


if __name__ == "__main__":
    unittest.main()

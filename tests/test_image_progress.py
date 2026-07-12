import unittest

from app.image_progress import ImageProgressPump


class _Page:
    def run_thread(self, handler):
        self.handler = handler


class _FailingPage:
    def run_thread(self, handler):
        raise RuntimeError("disconnected")


class _UnhashableControl:
    __hash__ = None

    def _refresh_progress(self):
        return False


class ImageProgressPumpTests(unittest.TestCase):
    def test_unhashable_control_can_register_and_unregister(self):
        page = _Page()
        pump = ImageProgressPump(page)
        control = _UnhashableControl()

        pump.register(control)
        pump.unregister(control)
        page.handler()

        self.assertFalse(pump._running)

    def test_failed_worker_start_does_not_leave_pump_running(self):
        page = _FailingPage()
        pump = ImageProgressPump(page)

        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            pump.register(_UnhashableControl())

        self.assertFalse(pump._running)


if __name__ == "__main__":
    unittest.main()

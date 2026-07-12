import unittest
from unittest.mock import Mock

from core.notification import Notification, Notifier


class NotificationTests(unittest.TestCase):
    def test_notifier_forwards_message(self):
        backend = Mock()
        notification = Notification("Title", "Body", "test")

        Notifier(backend).send(notification)

        backend.send.assert_called_once_with(notification)

    def test_backend_failure_does_not_escape(self):
        backend = Mock()
        backend.send.side_effect = RuntimeError("unavailable")

        Notifier(backend).send(Notification("Title", "Body"))

    def test_backend_failure_is_reported_when_logger_is_available(self):
        backend = Mock()
        backend.send.side_effect = RuntimeError("unavailable")
        log_exception = Mock()

        Notifier(backend, log_exception=log_exception).send(Notification("Title", "Body", "test.failed"))

        area, message = log_exception.call_args.args
        self.assertEqual(area, "通知")
        self.assertIn("test.failed", message)
        self.assertIn("unavailable", message)


if __name__ == "__main__":
    unittest.main()

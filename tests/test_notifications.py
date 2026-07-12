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


if __name__ == "__main__":
    unittest.main()

from app.debug_log import log_exception
from core.notification import Notification, Notifier


class PrintNotificationBackend:
    def send(self, notification: Notification) -> None:
        print(f"[通知][{notification.category}] {notification.title}：{notification.body}")


notifier = Notifier(PrintNotificationBackend(), log_exception=log_exception)


__all__ = ["Notification", "PrintNotificationBackend", "notifier"]

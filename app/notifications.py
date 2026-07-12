from core.notification import Notification, Notifier


class PrintNotificationBackend:
    def send(self, notification: Notification) -> None:
        print(f"[通知][{notification.category}] {notification.title}：{notification.body}")


notifier = Notifier(PrintNotificationBackend())


__all__ = ["Notification", "PrintNotificationBackend", "notifier"]

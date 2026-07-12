"""notification-service: decide who gets told what, and whether it is worth interrupting.

Ranks against open alerts, bundles related items, deduplicates by content fingerprint so
a re-scored risk is not re-sent, and routes above-bar items to channels while folding the
rest into a digest. Acked/snoozed targets stop re-firing (via user.actions).
"""

from cortex.services.notification.engine import Notification, NotificationEngine

__all__ = ["Notification", "NotificationEngine"]

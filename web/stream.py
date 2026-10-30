"""Event bus + SSE fan-out.

A single module-level EventBus is shared between the Flask app and any
code that publishes events (server callbacks, in 6c). Each SSE client
gets its own queue; publish() fans out to all of them.
"""

import queue
import threading
import time


class EventBus:
    def __init__(self, max_queue_size: int = 1000):
        self._lock = threading.Lock()
        self._subscribers: list = []
        self._max_queue_size = max_queue_size

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._max_queue_size)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def publish(self, event_type: str, data) -> None:
        msg = {"type": event_type, "data": data, "ts": time.time()}
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    # Slow client — drop it; EventSource will reconnect.
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


_bus = EventBus()


def get_bus() -> EventBus:
    return _bus

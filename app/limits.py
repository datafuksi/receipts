"""In-memory per-IP rate limit and a global daily cap. Resets on restart; fine for one container."""
import time
from collections import defaultdict, deque


class Limiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._day = ""
        self._day_count = 0

    def check(self, ip: str, per_min: int, daily_cap: int) -> str | None:
        """Return None if allowed, else a reason string."""
        now = time.time()
        today = time.strftime("%Y-%m-%d", time.gmtime(now))
        if today != self._day:
            self._day, self._day_count = today, 0
        if self._day_count >= daily_cap:
            return "daily_cap"
        q = self._hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= per_min:
            return "rate_limited"
        q.append(now)
        self._day_count += 1
        return None

    def reset(self) -> None:
        self._hits.clear()
        self._day_count = 0


limiter = Limiter()

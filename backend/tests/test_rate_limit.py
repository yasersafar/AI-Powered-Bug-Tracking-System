from app.core.rate_limit import SlidingWindowLimiter


def test_sliding_window_allows_then_blocks_then_recovers() -> None:
    limiter = SlidingWindowLimiter(max_attempts=2, window_seconds=10)
    assert limiter.hit("ip", now=0) is None
    assert limiter.hit("ip", now=1) is None
    assert limiter.hit("ip", now=2) == 8  # seconds until the oldest hit expires
    assert limiter.hit("other", now=2) is None  # keys are independent
    assert limiter.hit("ip", now=10.5) is None


def test_reset_clears_key() -> None:
    limiter = SlidingWindowLimiter(max_attempts=1, window_seconds=60)
    limiter.hit("ip", now=0)
    limiter.reset("ip")
    assert limiter.hit("ip", now=1) is None

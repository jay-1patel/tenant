import time
import threading
from collections import deque
from typing import Callable, Any
from functools import wraps

from routing.config import logger

class RateLimiter:
    """
    Token-based rate limiter for API calls to prevent hitting rate limits.
    Groq free tier: 6000 TPM (tokens per minute)
    Optimized for business WhatsApp bot with high volume.
    """

    def __init__(self, tokens_per_minute: int = 5800, safety_margin: float = 0.95):
        """
        Args:
            tokens_per_minute: Maximum tokens allowed per minute
            safety_margin: Safety margin (0.95 = use 95% of limit to be safe but maximize throughput)
        """
        self.tokens_per_minute = tokens_per_minute * safety_margin
        self.tokens_per_second = self.tokens_per_minute / 60
        self.min_interval = 0.5 / self.tokens_per_second  # Much more aggressive for business bot

        self.request_times = deque()
        self.lock = threading.Lock()
        self.total_requests = 0
        self.rate_limited_count = 0

        logger.info(f"RateLimiter initialized: {self.tokens_per_minute:.0f} TPM, min_interval: {self.min_interval:.3f}s")

    def acquire(self, estimated_tokens: int = 150) -> float:
        """
        Calculate wait time needed to stay within rate limit.

        Args:
            estimated_tokens: Estimated tokens this request will consume

        Returns:
            Seconds to wait before making the request
        """
        with self.lock:
            now = time.time()
            # Remove old request times (older than 1 minute)
            while self.request_times and self.request_times[0]['time'] < now - 60:
                self.request_times.popleft()

            # Calculate current tokens used in last minute (more realistic estimation)
            tokens_used = sum(req.get('tokens', 150) for req in self.request_times)

            # Calculate remaining budget
            remaining = self.tokens_per_minute - tokens_used

            if remaining >= estimated_tokens:
                # We have budget, minimal wait - more aggressive
                wait_time = max(0.1, self.min_interval)  # Reduced to 100ms minimum
            else:
                # Need to wait for budget to free up - MUCH more aggressive calculation
                deficit = estimated_tokens - remaining
                wait_time = min(2.0, (deficit / self.tokens_per_minute) * 5 + 0.2)
                self.rate_limited_count += 1
                logger.warning(f"⚠️ Rate limit: waiting {wait_time:.2f}s (deficit: {deficit:.0f} tokens, remaining: {remaining:.0f})")

            return max(0.05, wait_time)

    def record_request(self, estimated_tokens: int = 150):
        """Record that a request was made."""
        with self.lock:
            self.request_times.append({
                'time': time.time(),
                'tokens': estimated_tokens
            })
            self.total_requests += 1

    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        with self.lock:
            now = time.time()
            # Clean old requests
            while self.request_times and self.request_times[0]['time'] < now - 60:
                self.request_times.popleft()

            tokens_used = sum(req.get('tokens', 150) for req in self.request_times)

            return {
                'total_requests': self.total_requests,
                'rate_limited_count': self.rate_limited_count,
                'requests_last_minute': len(self.request_times),
                'tokens_used_last_minute': tokens_used,
                'tokens_remaining': max(0, self.tokens_per_minute / 0.7 - tokens_used),
                'utilization_percent': (tokens_used / (self.tokens_per_minute / 0.7)) * 100
            }

def rate_limit_limiter(rate_limiter: RateLimiter, estimated_tokens: int = 100):
    """
    Decorator to rate limit a function.

    Args:
        rate_limiter: RateLimiter instance
        estimated_tokens: Estimated tokens this request will consume
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Calculate wait time
            wait_time = rate_limiter.acquire(estimated_tokens)

            if wait_time > 0:
                logger.debug(f"Rate limiting: waiting {wait_time:.2f}s before {func.__name__}")
                time.sleep(wait_time)

            # Make the request
            try:
                result = func(*args, **kwargs)
                rate_limiter.record_request()
                return result
            except Exception as e:
                logger.warning(f"Request {func.__name__} failed: {e}")
                raise

        return wrapper
    return decorator

# Global rate limiter instance for Groq API - optimized for high throughput business bot
groq_rate_limiter = RateLimiter(tokens_per_minute=30000, safety_margin=0.95)
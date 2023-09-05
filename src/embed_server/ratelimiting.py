import logging

import redis
import time
import json
import hashlib
from fastapi import Request


class RateLimitHandler:
    """
    Handles the rate limiting for the embed server.
    """
    def __init__(
            self,
            *,
            buckets: dict[str, dict[str, int]] = None,
            **redis_kwargs,
    ):
        self.buckets = buckets or {
            "global": {
                "limit": 60,
                "expires": 30,
            },
            "generate": {
                "limit": 30,
                "expires": 30,
            },
            "create": {
                "limit": 10,
                "expires": 60,
            },
            "update": {
                "limit": 10,
                "expires": 60,
            },
            "delete": {
                "limit": 15,
                "expires": 60,
            },
        }
        self.redis = redis.Redis(**redis_kwargs)
        if not self.redis.ping():
            raise ConnectionError("Could not connect to Redis server.")

    def generate_ratelimit_headers(
            self,
            hits: int | Request,
            expires: float = 0,
            limit: int = 30,
            *,
            now: float = None,
            bucket: str | None = "global"
    ) -> dict[str, str]:
        """
        Generates the rate limit headers for the given parameters.

        :param hits: The current number of hits
        :param expires: The time when the rate limit expires
        :param limit: The maximum number of hits for this bucket
        :param now: The current time. Defaults to the time the function was called, which is usually close enough.
        :param bucket: The bucket name. Defaults to "global".
        :return: A dictionary containing the rate limit headers.
        """
        if isinstance(hits, Request):
            data = self.get(hits, bucket=bucket)
            hits = data["hits"]
            expires = data["expires"]
            limit = self.buckets[bucket]["limit"]

        if bucket is not None and not isinstance(bucket, str):
            raise TypeError("bucket must be a string or None")

        now = now or time.time()
        is_limited = hits > limit and expires > now
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Count": str(hits),
            "X-RateLimit-Remaining": str(limit - hits),
            "X-RateLimit-Reset": str(expires),
            "X-RateLimit-Reset-After": str(expires - now),
        }
        if bucket is not None:
            headers["X-RateLimit-Bucket"] = bucket
        if is_limited:
            logging.warning(f"Rate limit exceeded for bucket {bucket}!")
            headers["Retry-After"] = str(expires - now)
        return headers

    @staticmethod
    def calculate_key(client_ip: str, bucket: str = "global") -> str:
        """
        Generates an SHA256 hash of the client IP and the bucket name.

        :param client_ip: The client's IP address. Doesn't matter if its IPv4 or IPv6.
        :param bucket: The bucket name. Defaults to "global".
        :return: The hashed key.
        """
        # Since we aren't exactly doing security with these hashes, we won't bother with salting.
        # The idea of hashing in the first place is mainly for *some* sort of privacy.
        # We don't want to store the IP addresses in plaintext, after all.
        return hashlib.sha256(f"{client_ip}:{bucket}".encode("utf-8"), usedforsecurity=False).hexdigest()

    def set_json(self, key: str, data: dict | list) -> bool:
        """Calls Redis.set() but converts a JSON value for you."""
        value = json.dumps(
            data,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            default=None,
        )
        return self.redis.set(key, value.encode("utf-8"))

    def get(self, request: Request, *, bucket: str = "global") -> dict[str, str | int | float | bool]:
        """
        Gets the rate limit for the given request.

        :param request: The request to get the rate limit for.
        :param bucket: The bucket name. Defaults to "global".
        :return: A tuple containing the number of hits and the time the rate limit expires.
        """
        key = self.calculate_key(request.client.host, bucket)
        data: bytes | None = self.redis.get(key)
        if data is None:
            d = {
                "hits": 0,
                "expires": 0,
            }
        else:
            d = json.loads(data.decode("utf-8"))
        d["bucket"] = bucket
        return d

    def update(self, request: Request, *, bucket: str = "global") -> None:
        """
        Updates or sets the rate limit for the given request.

        :param request: The request to update the rate limit for.
        :param bucket: The bucket name. Defaults to "global".
        :return: Nothing
        """
        current_data = self.get(request, bucket=bucket)
        if current_data["expires"] <= time.time():
            current_data["hits"] = 0
            current_data["expires"] = 0

        current_data["hits"] += 1
        if current_data["expires"] == 0:
            current_data["expires"] = time.time() + self.buckets[bucket]["expires"]
        key = self.calculate_key(request.client.host, bucket)
        self.set_json(key, current_data)

    def check(self, request: Request, *, bucket: str = "global") -> bool:
        """
        Checks if the request is rate limited.

        :param request: The request to check the rate limit for.
        :param bucket: The bucket name. Defaults to "global".
        :return: True if the request is rate limited, False otherwise.
        """
        current_data = self.get(request, bucket=bucket)
        hits = current_data["hits"]
        expires = current_data["expires"]
        remaining = self.buckets[bucket]["limit"] - hits
        if expires > time.time() and remaining < 0:
            return True
        self.update(request)
        return False

    def remove(self, request: Request, *, bucket: str = "global") -> None:
        """
        Removes the rate limit for the given request.

        :param request: The request to remove the rate limit for.
        :param bucket: The bucket name. Defaults to "global".
        :return: Nothing
        """
        key = self.calculate_key(request.client.host, bucket)
        self.redis.delete(key)

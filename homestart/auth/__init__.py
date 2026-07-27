"""Authentication and persistent web sessions for HomeStart."""

from .manager import AuthManager
from .security import (
    LoginRateLimiter,
    address_in_networks,
    effective_client_ip,
    forwarded_https,
    normalize_cookie_secure_mode,
    normalize_trusted_proxies,
    trusted_proxy_networks,
)

__all__ = [
    "AuthManager",
    "LoginRateLimiter",
    "address_in_networks",
    "effective_client_ip",
    "forwarded_https",
    "normalize_cookie_secure_mode",
    "normalize_trusted_proxies",
    "trusted_proxy_networks",
]

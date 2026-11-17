"""Optional per-process IPv4-only resolution (FORCE_IPV4=1).

Why: some dev networks (DNS64/NAT64 with dead IPv6 routes) return unreachable
AAAA records for every host, and clients without a connect timeout stall on
them for minutes. Setting FORCE_IPV4=1 filters getaddrinfo to A records for
this process only — no system change needed.

Safe here: the DB URL uses a pinned IPv4 hostaddr, Supabase REST and HF hub
are IPv4-reachable, and TestClient uses 127.0.0.1.
"""

from __future__ import annotations

import logging
import os
import socket

logger = logging.getLogger("kaarigar.net")

_applied = False


def maybe_force_ipv4() -> None:
    global _applied
    if _applied or os.environ.get("FORCE_IPV4", "") != "1":
        return
    _applied = True
    _orig = socket.getaddrinfo

    def _ipv4_only(*args, **kwargs):
        return [r for r in _orig(*args, **kwargs) if r[0] == socket.AF_INET]

    socket.getaddrinfo = _ipv4_only
    logger.info("FORCE_IPV4=1 — getaddrinfo filtered to AF_INET for this process")

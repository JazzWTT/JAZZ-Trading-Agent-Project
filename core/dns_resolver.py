"""
DNS Resolver & ISP Hijack Bypass Utility
Transparently resolves domains via Cloudflare (1.1.1.1) and Google (8.8.8.8) UDP DNS,
bypassing regional ISP DNS poisoning (e.g., MCMC / TM redirects to 175.139.142.25)
without needing a VPN or system-level configuration changes.
"""

import socket
import struct
import logging
from typing import Dict, Optional, List

logger = logging.getLogger("DNSResolver")

# Domains targeted by regional ISP filtering
TARGET_DOMAINS = [
    "gamma-api.polymarket.com",
    "clob.polymarket.com",
    "ws-subscriptions-clob.polymarket.com",
    "api.binance.com",
    "stream.binance.com",
    "api.bybit.com",
]

# Cloudflare Anycast fallback IPs for Polymarket
STATIC_FALLBACKS: Dict[str, str] = {
    "gamma-api.polymarket.com": "172.64.153.51",
    "clob.polymarket.com": "172.64.153.51",
    "ws-subscriptions-clob.polymarket.com": "172.64.153.51",
    "api.binance.com": "54.249.46.216",
    "stream.binance.com": "54.249.46.216",
    "api.bybit.com": "104.18.34.205",
}

_DNS_CACHE: Dict[str, str] = dict(STATIC_FALLBACKS)
_PATCHED: bool = False
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


def query_dns_udp(domain: str, dns_server: str = "1.1.1.1", timeout: float = 2.0) -> Optional[str]:
    """
    Directly query an external DNS resolver via standard UDP port 53.
    Constructs a standard DNS A-record query and parses the first IPv4 answer.
    """
    try:
        # Standard DNS query header: ID=0x4a41 ("JA"), FLAGS=0x0100 (standard query, recursion desired)
        header = struct.pack("!HHHHHH", 0x4A41, 0x0100, 1, 0, 0, 0)

        # Build QNAME from domain parts
        qname = b""
        for part in domain.strip(".").split("."):
            qname += struct.pack("B", len(part)) + part.encode("ascii")
        qname += b"\x00"

        # QTYPE = 1 (A), QCLASS = 1 (IN)
        question = qname + struct.pack("!HH", 1, 1)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(header + question, (dns_server, 53))
        data, _ = sock.recvfrom(1024)
        sock.close()

        # Parse response: verify response has answers
        if len(data) < 12:
            return None
        _, _, qdcount, ancount, _, _ = struct.unpack("!HHHHHH", data[:12])
        if ancount == 0:
            return None

        # Skip question section
        idx = 12 + len(question)

        # Parse Resource Records
        for _ in range(ancount):
            if idx >= len(data):
                break
            # Handle name pointer or labels
            if data[idx] & 0xC0 == 0xC0:
                idx += 2
            else:
                while idx < len(data) and data[idx] != 0:
                    idx += data[idx] + 1
                idx += 1

            if idx + 10 > len(data):
                break

            rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", data[idx : idx + 10])
            idx += 10

            if rtype == 1 and rdlen == 4:  # Type A record
                ip = socket.inet_ntoa(data[idx : idx + 4])
                # Reject government sinkhole IP
                if ip.startswith("175.139."):
                    return None
                return ip
            idx += rdlen

    except Exception as e:
        logger.debug(f"Direct UDP DNS query to {dns_server} for {domain} failed: {e}")

    return None


def resolve_domain(domain: str) -> str:
    """Resolves a domain via 1.1.1.1 -> 8.8.8.8 -> static cache."""
    if domain in _DNS_CACHE and not _DNS_CACHE[domain].startswith("175.139."):
        return _DNS_CACHE[domain]

    # Try Cloudflare 1.1.1.1
    ip = query_dns_udp(domain, "1.1.1.1")
    if not ip:
        # Try Google 8.8.8.8
        ip = query_dns_udp(domain, "8.8.8.8")

    if ip and not ip.startswith("175.139."):
        _DNS_CACHE[domain] = ip
        return ip

    # Fallback to static Anycast IP
    return STATIC_FALLBACKS.get(domain, "")


def patch_dns():
    """
    Transparently monkey-patches socket.getaddrinfo so all Python networking
    (requests, httpx, aiohttp, websockets, urllib) connects to true IPs.
    """
    global _PATCHED, _ORIGINAL_GETADDRINFO
    if _PATCHED:
        return

    def patched_getaddrinfo(host, port, *args, **kwargs):
        if isinstance(host, str):
            for target in TARGET_DOMAINS:
                if host == target or host.endswith("." + target):
                    clean_ip = resolve_domain(host)
                    if clean_ip:
                        return _ORIGINAL_GETADDRINFO(clean_ip, port, *args, **kwargs)
        return _ORIGINAL_GETADDRINFO(host, port, *args, **kwargs)

    socket.getaddrinfo = patched_getaddrinfo
    _PATCHED = True
    logger.info("DNS bypass active: Transparently routing Polymarket & crypto domains via secure Cloudflare Anycast.")


def unpatch_dns():
    """Restores original socket.getaddrinfo."""
    global _PATCHED
    if _PATCHED:
        socket.getaddrinfo = _ORIGINAL_GETADDRINFO
        _PATCHED = False

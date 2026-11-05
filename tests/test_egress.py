"""Exercise the real guard parsers without giving tests an external route."""

import asyncio

import httpx
from dnslib import DNSRecord, RCODE

from services.egress.guard import EgressGuard


class Writer:
    def __init__(self):
        self.output = bytearray()

    def get_extra_info(self, key):
        return ("172.30.0.2", 12345)

    def write(self, data):
        self.output.extend(data)

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


def test_proxy_allows_only_exact_get_and_checks_encoded_canary():
    async def run():
        events, leaks, forwarded = [], [], []

        async def canary(text, twin, channel):
            if "canary123" in text:
                leaks.append(channel)
                return True
            return False

        guard = EgressGuard("demo.test", "192.0.2.1", lambda ip: "twin", canary,
                            lambda twin, kind, **fields: events.append(fields))
        await guard.client.aclose()

        async def fetch(request):
            forwarded.append(str(request.url))
            return httpx.Response(200, text="fixture")

        guard.client = httpx.AsyncClient(transport=httpx.MockTransport(fetch))
        for target, method, status in [
            ("http://demo.test/", "GET", 200),
            ("http://demo.test/diagnostics", "GET", 200),
            ("http://demo.test/", "POST", 403),
            ("http://demo.test/?leak=x", "GET", 403),
            ("http://demo.test.evil/", "GET", 403),
            ("example.com:443", "CONNECT", 403),
            ("http://demo.test/%63anary123", "GET", 403),
        ]:
            reader, writer = asyncio.StreamReader(), Writer()
            reader.feed_data(f"{method} {target} HTTP/1.1\r\nHost: demo.test\r\n\r\n".encode())
            reader.feed_eof()
            await guard.proxy(reader, writer)
            assert writer.output.startswith(f"HTTP/1.1 {status}".encode())
        assert len(forwarded) == 2
        assert leaks == ["http"]
        assert len(events) == 7
        await guard.client.aclose()

    asyncio.run(run())


def test_dns_default_deny_and_tripwire_even_for_unlisted_domain():
    async def run():
        matched = []

        async def canary(text, twin, channel):
            if "canary123" in text:
                matched.append((twin, channel))
                return True
            return False

        guard = EgressGuard("demo.test", "192.0.2.1", lambda ip: "twin", canary, lambda *a, **k: None)
        for host, expected in [("demo.test", RCODE.NOERROR), ("example.com", RCODE.NXDOMAIN),
                                ("canary123.evil.test", RCODE.NXDOMAIN)]:
            response = DNSRecord.parse(await guard.dns_reply(DNSRecord.question(host).pack(), "172.30.0.2"))
            assert response.header.rcode == expected
            if host == "demo.test":
                assert str(response.rr[0].rdata) == "192.0.2.1"
        assert matched == [("twin", "dns")]
        await guard.client.aclose()

    asyncio.run(run())

"""Default-deny HTTP proxy and DNS. HTTPS CONNECT is never tunnelled."""

import asyncio
from urllib.parse import unquote, urlsplit

import httpx
from dnslib import A, DNSRecord, QTYPE, RCODE, RR


class DNSGuard(asyncio.DatagramProtocol):
    def __init__(self, guard):
        self.guard = guard

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.create_task(self.answer(data, addr))

    async def answer(self, data, addr):
        try:
            self.transport.sendto(await self.guard.dns_reply(data, addr[0]), addr)
        except Exception:
            return


class EgressGuard:
    def __init__(self, domain, control_ip, owner_for_ip, canary, event):
        self.domain = domain
        self.control_ip = control_ip
        self.owner_for_ip = owner_for_ip
        self.canary = canary
        self.event = event
        self.client = httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=10)

    async def dns_reply(self, data, ip):
        request = DNSRecord.parse(data)
        host = str(request.q.qname).rstrip(".").lower()
        twin = self.owner_for_ip(ip)
        compromised = await self.canary(host, twin, "dns")
        allowed = bool(twin and not compromised and host == self.domain and request.q.qtype == QTYPE.A)
        self.event(twin, "dns", host="<canary redacted>" if compromised else host, allowed=allowed)
        reply = request.reply()
        if allowed:
            reply.add_answer(RR(host, QTYPE.A, rdata=A(self.control_ip), ttl=10))
        else:
            reply.header.rcode = RCODE.NXDOMAIN
        return reply.pack()

    async def dns_tcp(self, reader, writer):
        try:
            size = int.from_bytes(await asyncio.wait_for(reader.readexactly(2), 3), "big")
            if size > 4096:
                return
            data = await asyncio.wait_for(reader.readexactly(size), 3)
            response = await self.dns_reply(data, writer.get_extra_info("peername")[0])
            writer.write(len(response).to_bytes(2, "big") + response)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def proxy(self, reader, writer):
        peer = writer.get_extra_info("peername")
        twin = self.owner_for_ip(peer[0]) if peer else None
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            if len(raw) > 32768:
                raise ValueError("Header limit")
            lines = raw.decode("latin1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.lower()] = value.strip()
            size = int(headers.get("content-length", "0"))
            if not 0 <= size <= 16384 or "transfer-encoding" in headers:
                raise ValueError("Body limit")
            body = await asyncio.wait_for(reader.readexactly(size), timeout=5) if size else b""
            inspected = unquote(raw.decode("latin1") + body.decode("latin1"))
            if await self.canary(inspected, twin, "http"):
                await self.reply(writer, 403, b"Canary tripwire: twin terminated")
                return
            parsed = urlsplit(target)
            allowed = (twin is not None and method == "GET" and parsed.scheme == "http" and parsed.hostname == self.domain
                       and parsed.port in (None, 80) and parsed.path in ("", "/", "/diagnostics")
                       and not parsed.query and not body)
            self.event(twin, "http", host=parsed.hostname or target, method=method,
                       path=parsed.path, allowed=allowed, bytes=len(raw) + len(body))
            if not allowed:
                await self.reply(writer, 403, b"Default-deny egress policy")
                return
            response = await self.client.get("http://" + self.control_ip + (parsed.path or "/"),
                                              headers={"Host": self.domain})
            await self.reply(writer, response.status_code, response.content,
                             response.headers.get("content-type", "text/html"))
        except Exception:
            with __import__("contextlib").suppress(Exception):
                await self.reply(writer, 400, b"Invalid proxy request")
        finally:
            writer.close()
            with __import__("contextlib").suppress(Exception):
                await writer.wait_closed()

    @staticmethod
    async def reply(writer, status, body, content_type="text/plain"):
        writer.write((f"HTTP/1.1 {status} Callback\r\nContent-Length: {len(body)}\r\n"
                      f"Content-Type: {content_type}\r\nConnection: close\r\n\r\n").encode() + body)
        await writer.drain()

    async def start(self):
        server = await asyncio.start_server(self.proxy, "172.30.0.1", 3128, limit=32768)
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: DNSGuard(self), local_addr=("172.30.0.1", 53))
        dns_tcp = await asyncio.start_server(self.dns_tcp, "172.30.0.1", 53)
        return server, transport, dns_tcp

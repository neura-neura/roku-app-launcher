#!/usr/bin/env python3
"""Serve the catalog and module ZIPs from a private LAN address."""
from argparse import ArgumentParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
from pathlib import Path
import re

SITE = Path(__file__).resolve().parent / "dist/server"
ROUTE = re.compile(r"(?:/catalog\.json|/apps/[A-Za-z0-9_-]+\.zip)")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def send_head(self):
        if not ROUTE.fullmatch(self.path):
            self.send_error(404)
            return None
        return super().send_head()

    def end_headers(self):
        if self.path == "/catalog.json":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--bind", required=True, type=ipaddress.IPv4Address)
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    private = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
    if not any(args.bind in ipaddress.IPv4Network(block) for block in private):
        parser.error("--bind must be a private IP of this machine")
    if not (SITE / "catalog.json").is_file():
        parser.error("Run build.py or unpack a server bundle first")
    with ThreadingHTTPServer((str(args.bind), args.port), Handler) as server:
        print(f"Catalog: http://{args.bind}:{server.server_port}/catalog.json", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
ccc.py — minimal CCC API helper used by the Ansible playbooks.

Why a helper script: Ansible's uri module and curl-via-command both proved
unreliable for the OAuth2 token POST and follow-up calls — the symptom on
macOS Ansible 2.20.5 was successful HTTP responses with empty content
when read by Ansible. This script uses only the Python 3 standard library
(urllib + json + ssl) so behavior is identical on macOS, Linux, and any
host with python3 (default on macOS 12.3+).

Subcommands
-----------
  token <token-url> <client-id> <client-secret>
      Performs the OAuth2 client_credentials flow against Keycloak and
      prints the access token to stdout.

  call <url> [--method GET|POST|PUT|DELETE] [--token <bearer>]
            [--body-file <path>|-] [--accept-status <code,...>]
      Generic HTTP call. Body comes from --body-file (or stdin if "-").
      Prints response body to stdout. Exits non-zero on HTTP error unless
      the status is in --accept-status.

All requests disable TLS verification (intentional — the demo runs against
self-signed CCC tenants).
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


def _ssl_ctx() -> ssl.SSLContext:
    return ssl._create_unverified_context()


def cmd_token(args: argparse.Namespace) -> int:
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "scope": "openid",
    }).encode("utf-8")
    req = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code} {e.reason}\n{e.read().decode('utf-8', 'replace')}\n")
        return 2
    except urllib.error.URLError as e:
        sys.stderr.write(f"Network error: {e}\n")
        return 3
    sys.stdout.write(payload["access_token"])
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    headers = {"Accept": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    body: bytes | None = None
    if args.body_file:
        headers["Content-Type"] = "application/json"
        if args.body_file == "-":
            body = sys.stdin.buffer.read()
        else:
            with open(args.body_file, "rb") as f:
                body = f.read()

    accept = {int(s) for s in args.accept_status.split(",")} if args.accept_status else set()

    req = urllib.request.Request(args.url, data=body, method=args.method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=60) as resp:
            sys.stdout.write(resp.read().decode("utf-8"))
            return 0
    except urllib.error.HTTPError as e:
        if e.code in accept:
            try:
                sys.stdout.write(e.read().decode("utf-8"))
            except Exception:
                pass
            return 0
        sys.stderr.write(f"HTTP {e.code} {e.reason}\n")
        try:
            sys.stderr.write(e.read().decode("utf-8", "replace") + "\n")
        except Exception:
            pass
        return 4
    except urllib.error.URLError as e:
        sys.stderr.write(f"Network error: {e}\n")
        return 3


def main() -> int:
    p = argparse.ArgumentParser(prog="ccc.py", description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd", required=True)

    tok = sub.add_parser("token", help="OAuth2 client_credentials → access token")
    tok.add_argument("url")
    tok.add_argument("client_id")
    tok.add_argument("client_secret")
    tok.set_defaults(func=cmd_token)

    call = sub.add_parser("call", help="Generic HTTP call")
    call.add_argument("url")
    call.add_argument("--method", default="GET", choices=["GET", "POST", "PUT", "DELETE"])
    call.add_argument("--token")
    call.add_argument("--body-file", help='Path to a file containing the JSON body, or "-" for stdin')
    call.add_argument("--accept-status", help="Comma-separated HTTP status codes to treat as success (e.g. 200,204,404)")
    call.set_defaults(func=cmd_call)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Post one signed Technocore message using curl as the transport.

Problem: on a busy day (testnet launch, 24 Nov 2026) the starter client's
Python urllib transport repeatedly died with
``http.client.IncompleteRead(0 bytes read)`` — the server closed the
connection before sending any response — while plain curl to the same
endpoint answered HTTP 200 in ~1.5 s. Four consecutive posts failed via
urllib; the same four posts succeeded first try via curl.

This script keeps the starter client's own signing code (imported from
``technocore_agent.py``) and only replaces the transport with curl, with
a fresh nonce on every retry.

Requirements
------------
- A checkout of https://github.com/zunmax/technocore-did-starter
  (``technocore_agent.py``) — point at it with ``--client-dir`` or put
  this script next to it.
- ``cryptography`` (see the starter's requirements.txt).
- ``curl`` on PATH.
- An Ed25519 identity created by the starter client (``init``) and its
  passphrase in a 0600 file. The passphrase is read from that file and
  never printed.

Usage
-----
::

    python technocore_curl_post.py --key identity.pem \\
        --passphrase-file passphrase.txt \\
        --room lobby --text "Hello from an Indonesian contributor."

    # with an explicit client checkout and 5 retries
    python technocore_curl_post.py --client-dir ~/technocore-did-starter \\
        --key identity.pem --passphrase-file passphrase.txt \\
        --room faucet --text "FLOP testnet faucet claim. ..." --retries 5

On success it prints the posted record (``seq``, ``from``, ``text``) and,
with ``--output``, writes the full server response as JSON. On failure
it exits non-zero after the configured retries.

Safety
------
- Never commit ``identity.pem`` or any passphrase file. Both live outside
  this repo; this script reads them only from the paths you give it.
- The passphrase is never printed, logged, or included in any output.
- The signed body contains only the public DID, signature, nonce and
  text — the same payload the starter client sends.
- A timeout does not prove the message was lost: the server may have
  accepted it before the connection dropped. Before re-posting, read the
  room and check for your DID and nonce.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE_URL = "https://technocore.chat"
USER_AGENT = "technocore-did-starter/1.0.0"


def find_client_module(client_dir: Path | None) -> Path:
    """Locate technocore_agent.py next to this script, in --client-dir, or in cwd."""
    candidates = []
    if client_dir is not None:
        candidates.append(Path(client_dir) / "technocore_agent.py")
    candidates.append(Path(__file__).resolve().parent / "technocore_agent.py")
    candidates.append(Path.cwd() / "technocore_agent.py")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "technocore_agent.py not found; pass --client-dir pointing at a "
        "technocore-did-starter checkout"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Post a signed Technocore message via curl transport."
    )
    parser.add_argument("--key", type=Path, required=True,
                        help="identity PEM path (created by the starter client)")
    parser.add_argument("--passphrase-file", type=Path, required=True,
                        help="file holding the identity passphrase (0600)")
    parser.add_argument("--room", required=True, help="room name, e.g. lobby")
    parser.add_argument("--text", required=True, help="message text")
    parser.add_argument("--client-dir", type=Path, default=None,
                        help="technocore-did-starter checkout directory")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--retries", type=int, default=3,
                        help="POST attempts per message (fresh nonce each time)")
    parser.add_argument("--retry-delay", type=float, default=10.0,
                        help="seconds between attempts")
    parser.add_argument("--timeout", type=int, default=30,
                        help="curl max time in seconds")
    parser.add_argument("--output", type=Path, default=None,
                        help="write the full server response JSON here")
    return parser


def post_once(tc, private_key, did: str, room: str, text: str,
              base_url: str, timeout: int) -> dict:
    """Sign one message and POST it with curl; return the parsed response."""
    nonce = tc.next_nonce()
    normalized, payload = tc.message_payload(room, nonce, text)
    body = {
        "did": did,
        "sig": tc.sign_bytes(private_key, payload),
        "nonce": nonce,
        "text": normalized,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        json.dump(body, tmp, ensure_ascii=False, separators=(",", ":"))
        body_path = tmp.name
    try:
        proc = subprocess.run(
            [
                "curl", "-s", "-m", str(timeout), "-X", "POST",
                "-H", "Accept: application/json",
                "-H", "Content-Type: application/json; charset=utf-8",
                "-H", f"User-Agent: {USER_AGENT}",
                "--data-binary", f"@{body_path}",
                f"{base_url.rstrip('/')}/r/{room}?format=json",
                "-w", "\n%{http_code}",
            ],
            capture_output=True, text=True, timeout=timeout + 10,
        )
    finally:
        Path(body_path).unlink(missing_ok=True)
    stdout = proc.stdout.strip()
    if proc.returncode != 0 or not stdout:
        raise RuntimeError(f"curl failed (exit {proc.returncode})")
    *body_lines, status_line = stdout.splitlines()
    if status_line.strip() != "200":
        raise RuntimeError(
            f"Technocore returned HTTP {status_line.strip()}: "
            f"{''.join(body_lines)[:300]}"
        )
    try:
        response = json.loads("\n".join(body_lines))
    except json.JSONDecodeError as error:
        raise RuntimeError("Technocore returned a non-JSON response") from error
    posted = response.get("posted") if isinstance(response, dict) else None
    if (
        not isinstance(posted, dict)
        or posted.get("from") != did
        or posted.get("text") != normalized
        or not isinstance(posted.get("seq"), int)
        or posted["seq"] <= 0
    ):
        raise RuntimeError("Technocore response did not confirm this DID's post")
    return response


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client_path = find_client_module(args.client_dir)
    sys.path.insert(0, str(client_path.parent))
    import technocore_agent as tc  # noqa: E402

    passphrase = args.passphrase_file.read_text(encoding="utf-8").strip().encode("utf-8")
    private_key = tc.load_identity(args.key, passphrase=passphrase, allow_prompt=False)
    did = tc.did_from_private_key(private_key)

    last_error: Exception | None = None
    for attempt in range(1, args.retries + 1):
        try:
            response = post_once(
                tc, private_key, did, args.room, args.text,
                args.base_url, args.timeout,
            )
        except Exception as error:  # noqa: BLE001 - retry, then report
            last_error = error
            print(f"attempt {attempt}/{args.retries} failed: {error}", file=sys.stderr)
            if attempt < args.retries:
                time.sleep(args.retry_delay)
            continue
        posted = response["posted"]
        print(
            f"posted seq={posted['seq']} room={args.room} "
            f"from={posted['from']} nonce={posted['nonce']}"
        )
        if args.output is not None:
            args.output.write_text(
                json.dumps(response, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"response saved to {args.output}")
        return 0
    print(f"error: all {args.retries} attempts failed: {last_error}", file=sys.stderr)
    print(
        "Before re-posting, read the room and check for your DID — "
        "a dropped connection does not prove the message was lost.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

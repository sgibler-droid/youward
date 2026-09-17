#!/usr/bin/env python3
"""Post one receipt line without placing the repository-secret webhook in logs."""

import json
import os
import pathlib
import sys
import urllib.request


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: post-slack-receipt.py RECEIPT_JSON")
    webhook = os.environ.get("YOUWARD_SLACK_WEBHOOK", "")
    if not webhook:
        raise SystemExit("YOUWARD_SLACK_WEBHOOK repository secret is not configured")
    receipt = json.loads(pathlib.Path(sys.argv[1]).read_text())
    body = json.dumps({"text": receipt["receipt_line"]}).encode()
    request = urllib.request.Request(
        webhook, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        if not 200 <= response.status < 300:
            raise SystemExit(f"Slack receipt failed with HTTP {response.status}")
    print("Slack receipt: posted")


if __name__ == "__main__":
    main()

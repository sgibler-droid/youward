#!/usr/bin/env python3
"""Fail when publishable page or captured workflow logs contain P44 leak signals."""

import argparse
import pathlib
import re
import sys

RULES = {
    "private user path": re.compile(r"(?:/Users/[^/\s]+|[A-Za-z]:\\Users\\[^\\\s]+)"),
    "OpenClaw private path": re.compile(r"\.openclaw|youward-cache", re.I),
    "private API field": re.compile(r"publisherUid", re.I),
    "authorization/token": re.compile(
        r"(?:authorization\s*:\s*bearer|hooks\.slack\.com/services/|"
        r"\bgh[pousr]_[A-Za-z0-9_]{12,}|\bAKIA[0-9A-Z]{16}\b|"
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
        r"(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*['\"]?[^\s'\"]{8,})",
        re.I),
    "email address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "phone number": re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)"),
}


def scan(path):
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    findings = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for label, pattern in RULES.items():
            if pattern.search(line):
                findings.append((str(path), line_no, label))
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    findings = []
    for path in args.paths:
        findings.extend(scan(path))
    if findings:
        for path, line_no, label in findings:
            print(f"P44 LEAK: {path}:{line_no}: {label}")
        return 1
    print(f"P44 leak gate: PASS ({len(args.paths)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

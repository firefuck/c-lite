"""Stdlib Airtable client for the ``airtable`` skill.

The token is read inside this process (env var, else ``<home>/.secrets.json``) and
sent over HTTPS only, so it never appears on a command line, in shell history, or
in ``ps`` output. Nothing beyond Python 3 is required.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.airtable.com/v0"


def home() -> Path:
    val = os.environ.get("CLITE_HOME", "").strip()
    return Path(val) if val else Path.home() / ".clite"


def _token() -> str:
    value = os.environ.get("AIRTABLE_API_KEY", "").strip()
    if value:
        return value
    secret_file = home() / ".secrets.json"
    try:
        data = json.loads(secret_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(
            f'airtable: cannot read {secret_file}: {exc}\nWrite it first: {{"AIRTABLE_API_KEY": "pat_..."}}'
        )
    value = str(data.get("AIRTABLE_API_KEY", "")).strip()
    if not value:
        sys.exit(
            f"airtable: AIRTABLE_API_KEY missing from {secret_file}\n"
            'Write it first: {"AIRTABLE_API_KEY": "pat_..."}'
        )
    return value


def request(method: str, path: str, body: dict | None = None) -> dict:
    payload = json.dumps(body).encode() if body is not None else None
    auth = "Bearer " + _token()
    req = urllib.request.Request(
        API + path,
        data=payload,
        method=method,
        headers={"Authorization": auth, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        sys.exit(f"airtable: HTTP {exc.code} {exc.reason}\n{detail}")


def payload_from_file(args: argparse.Namespace) -> dict:
    if not args.json_file:
        sys.exit("airtable: --json-file with the request fields is required")
    return json.loads(Path(args.json_file).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(prog="atr.py", description=__doc__.splitlines()[0])
    parser.add_argument(
        "action",
        choices=["bases", "tables", "list", "get", "create", "update", "upsert", "delete"],
    )
    parser.add_argument("--base", default=os.environ.get("AIRTABLE_BASE_ID", ""))
    parser.add_argument("--table", default="")
    parser.add_argument("--id", default="")
    parser.add_argument("--json-file", default="")
    parser.add_argument("--formula", default="")
    parser.add_argument("--max-records", type=int, default=100)
    parser.add_argument("--field", default="Name")
    args = parser.parse_args()

    _token()  # fail fast before any network call

    table = urllib.parse.quote(args.table)
    if args.action == "bases":
        out = request("GET", "/meta/bases")
    elif args.action == "tables":
        out = request("GET", f"/meta/bases/{args.base}/tables")
    elif args.action == "list":
        query = f"?maxRecords={args.max_records}"
        if args.formula:
            query += "&filterByFormula=" + urllib.parse.quote(args.formula)
        out = request("GET", f"/{args.base}/{table}{query}")
    elif args.action == "get":
        out = request("GET", f"/{args.base}/{table}/{args.id}")
    elif args.action == "create":
        out = request("POST", f"/{args.base}/{table}", payload_from_file(args))
    elif args.action == "update":
        out = request("PATCH", f"/{args.base}/{table}/{args.id}", payload_from_file(args))
    elif args.action == "upsert":
        body = payload_from_file(args)
        records = body.get("records") or [body]
        out = request(
            "POST",
            f"/{args.base}/{table}",
            {"records": records, "performUpsert": {"fieldsToMergeOn": [args.field]}},
        )
    else:  # delete
        out = request("DELETE", f"/{args.base}/{table}/{args.id}")

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

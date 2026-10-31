"""Command-line interface: ``browserprofile <command> [options]``."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from rich.console import Console
from rich.table import Table

from . import (
    build_checkpoint,
    diff_checkpoints,
    extract_autofill,
    extract_bookmarks,
    extract_cookies,
    extract_credit_cards,
    extract_history,
    extract_logins,
    list_profiles,
)
from .checkpoint import SECRET_MODES
from .errors import BrowserProfileError
from .logger import Logger

# command -> (extractor, [(column header, record attribute), ...])
_COMMANDS = {
    "cookies": (extract_cookies, [
        ("host", "host"), ("name", "name"), ("value", "value"),
        ("secure", "secure"), ("expires", "expires")]),
    "history": (extract_history, [
        ("last visit", "last_visit"), ("visits", "visit_count"),
        ("title", "title"), ("url", "url")]),
    "bookmarks": (extract_bookmarks, [
        ("added", "date_added"), ("folder", "folder"),
        ("title", "title"), ("url", "url")]),
    "autofill": (extract_autofill, [
        ("field", "field_name"), ("value", "value"),
        ("count", "use_count"), ("last used", "last_used")]),
    "passwords": (extract_logins, [
        ("url", "url"), ("username", "username"), ("password", "password")]),
    "cards": (extract_credit_cards, [
        ("name", "name_on_card"), ("month", "expiration_month"),
        ("year", "expiration_year"), ("number", "card_number")]),
}


def _select_profiles(browser, profile_filter):
    profiles = list_profiles(browser)
    if profile_filter:
        profiles = [p for p in profiles if profile_filter in (p.name, str(p.path))]
    return profiles


def _truncate(value, width=60):
    text = "" if value is None else str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def _cmd_profiles(args, console):
    profiles = _select_profiles(args.browser, args.profile)
    if args.json:
        console.print_json(json.dumps([
            {"browser": p.browser, "family": p.family, "name": p.name, "path": str(p.path)}
            for p in profiles]))
        return
    table = Table(title="Detected browser profiles")
    for header in ("browser", "family", "profile", "path"):
        table.add_column(header, overflow="fold")
    for p in profiles:
        table.add_row(p.browser, p.family, p.name, str(p.path))
    console.print(table)


def _cmd_extract(args, console):
    extractor, columns = _COMMANDS[args.command]
    logger = Logger(level=logging.DEBUG if args.verbose else logging.WARNING)

    keyring = args.keyring.upper() if args.keyring else None
    records = []
    for profile in _select_profiles(args.browser, args.profile):
        try:
            records.extend(extractor(profile, logger, keyring=keyring))
        except BrowserProfileError as e:
            logger.warning(f"{profile.label}: {e}")
        except Exception as e:  # per-profile robustness: one bad DB shouldn't abort all
            logger.warning(f"{profile.label}: unexpected error: {e}")

    if args.limit:
        records = records[: args.limit]

    if args.json:
        console.print_json(json.dumps([r.to_dict() for r in records]))
        return

    table = Table(title=f"{args.command} ({len(records)} rows)")
    table.add_column("browser")
    table.add_column("profile")
    for header, _ in columns:
        table.add_column(header, overflow="fold")
    for r in records:
        table.add_row(r.browser, r.profile, *(_truncate(getattr(r, attr)) for _, attr in columns))
    console.print(table)


def _cmd_checkpoint(args, console):
    logger = Logger(level=logging.DEBUG if args.verbose else logging.WARNING)
    keyring = args.keyring.upper() if args.keyring else None
    checkpoint = build_checkpoint(
        _select_profiles(args.browser, args.profile),
        secrets=args.secrets, logger=logger, keyring=keyring)
    text = json.dumps(checkpoint, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf8") as f:
            f.write(text)
        counts = ", ".join(f"{kind} {len(rows)}" for kind, rows in checkpoint["records"].items())
        print(f"wrote {args.output} (secrets={args.secrets}): {counts}", file=sys.stderr)
    else:
        print(text)


def _cmd_diff(args, console):
    with open(args.before, encoding="utf8") as f:
        before = json.load(f)
    with open(args.after, encoding="utf8") as f:
        after = json.load(f)
    diff = diff_checkpoints(before, after)

    if args.json:
        print(json.dumps(diff, indent=2))
        return

    table = Table(title=f"{args.before} → {args.after}")
    for header in ("data", "added", "removed", "changed"):
        table.add_column(header, justify="right" if header != "data" else "left")
    for kind, delta in diff.items():
        if not any(delta.values()):
            continue
        table.add_row(kind, str(len(delta["added"])), str(len(delta["removed"])), str(len(delta["changed"])))
    console.print(table)
    for kind, delta in diff.items():
        for row in delta["changed"]:
            key = " ".join(f"{k}={v}" for k, v in row["key"].items() if v)
            console.print(f"  ~ {kind}: {_truncate(key, 70)} ({', '.join(row['changed_fields'])})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="browserprofile",
        description="Detect local browser profiles and extract their on-disk data.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_profiles = sub.add_parser("profiles", help="list detected browser profiles")
    for p in (p_profiles, *[sub.add_parser(name, help=f"extract {name}") for name in _COMMANDS]):
        p.add_argument("-b", "--browser", help="restrict to one browser (e.g. chrome, firefox)")
        p.add_argument("-p", "--profile", help="restrict to one profile (name or path)")
        p.add_argument("--json", action="store_true", help="output JSON instead of a table")
        p.add_argument("-v", "--verbose", action="store_true", help="verbose logging to stderr")
        if p is not p_profiles:
            p.add_argument("-n", "--limit", type=int, help="show at most N rows")
            p.add_argument(
                "--keyring", metavar="NAME",
                help="force the Linux keyring backend for Chromium decryption "
                     "(KWALLET, KWALLET5, KWALLET6, GNOMEKEYRING, BASICTEXT) when "
                     "auto-detection fails outside a desktop session")

    p_checkpoint = sub.add_parser("checkpoint", help="snapshot all profile data to JSON")
    p_checkpoint.add_argument("-b", "--browser", help="restrict to one browser (e.g. chrome, firefox)")
    p_checkpoint.add_argument("-p", "--profile", help="restrict to one profile (name or path)")
    p_checkpoint.add_argument("-v", "--verbose", action="store_true", help="verbose logging to stderr")
    p_checkpoint.add_argument("--keyring", metavar="NAME", help="force the Linux keyring backend")
    p_checkpoint.add_argument(
        "--secrets", choices=SECRET_MODES, default="hash",
        help="how to store cookie values / passwords / card numbers (default: hash)")
    p_checkpoint.add_argument("-o", "--output", metavar="FILE", help="write to FILE instead of stdout")

    p_diff = sub.add_parser("diff", help="show what changed between two checkpoints")
    p_diff.add_argument("before", help="earlier checkpoint JSON file")
    p_diff.add_argument("after", help="later checkpoint JSON file")
    p_diff.add_argument("--json", action="store_true", help="output JSON instead of a table")

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    try:
        if args.command == "profiles":
            _cmd_profiles(args, console)
        elif args.command == "checkpoint":
            _cmd_checkpoint(args, console)
        elif args.command == "diff":
            _cmd_diff(args, console)
        else:
            _cmd_extract(args, console)
    except BrowserProfileError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

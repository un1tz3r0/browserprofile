"""Command-line interface: ``browserprofile <command> [options]``."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from rich.console import Console
from rich.table import Table

from . import (
    extract_autofill,
    extract_bookmarks,
    extract_cookies,
    extract_credit_cards,
    extract_history,
    extract_logins,
    list_profiles,
)
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

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    try:
        if args.command == "profiles":
            _cmd_profiles(args, console)
        else:
            _cmd_extract(args, console)
    except BrowserProfileError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

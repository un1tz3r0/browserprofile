# browserprofile

### Overview

A self-contained, low-dependency python package which provides programmatic, non-interactive access to local web-browser profile data.

Detects local profiles created by popular web-browsers, and extracts (and decrypts) the data stored in them.

For details -- specifically: the definition of "data stored in them" and "popular web-browsers" -- see the table below.

### Feature Matrix

| Data           | Chromium (Chrome/Chromium/Brave/Edge/Opera/Vivaldi/Whale) | Firefox |
|----------------|-----------------------------------------------------------|---------|
| Cookies        | ✅ (decrypted)                                            | ✅      |
| History        | ✅                                                        | ✅      |
| Bookmarks      | ✅                                                        | ✅      |
| Form autofill  | ✅                                                        | ✅      |
| Saved passwords| ✅ (decrypted)                                            | ✅ (NSS, no master password) |
| Credit cards   | ✅ (decrypted)                                            | — (not stored) |

## Notices

The profile-detection, profile-location and Chromium cookie decryption code is
**ported from [yt-dlp](https://github.com/yt-dlp/yt-dlp)** (`yt_dlp/cookies.py`,
public domain / Unlicense) and extended with the additional data extractors and
Firefox login decryption. See `NOTICE`.

It only reads your **own** local browser data on the machine it runs on. It does
no network access.

# Quick Start

## Install / run (uv)

```bash
uv sync                      # create the venv and install deps
uv run browserprofile --help
```

## CLI

```bash
uv run browserprofile profiles                 # list detected profiles
uv run browserprofile history  -b chrome -n 20 # 20 most recent Chrome history rows
uv run browserprofile bookmarks -b firefox
uv run browserprofile cookies  -b chrome --json
uv run browserprofile passwords -b chrome
uv run browserprofile autofill
uv run browserprofile cards -b chrome
```

Common options for the extract commands:

- `-b/--browser` — restrict to one browser (`chrome`, `firefox`, `brave`, …)
- `-p/--profile` — restrict to one profile (by name or path)
- `-n/--limit` — cap the number of rows shown
- `--json` — emit JSON instead of a table
- `--keyring NAME` — force the Linux keyring backend (see note below)
- `-v/--verbose` — debug logging to stderr

### Linux keyring note

Chromium encrypts cookies / passwords with a key stored in the OS secret service
(GNOME Keyring or KWallet). The backend is auto-detected from the desktop-session
environment variables. **If you run this outside your graphical session** (e.g.
over plain SSH or from a service where `XDG_CURRENT_DESKTOP` is unset), detection
falls back to `BASICTEXT` and keyring-encrypted (`v11`) values cannot be
decrypted. To force the right backend explicitly:

```bash
uv run browserprofile cookies -b chrome --keyring GNOMEKEYRING
```

Valid values: `GNOMEKEYRING`, `KWALLET`, `KWALLET5`, `KWALLET6`, `BASICTEXT`.

## Library

```python
import browserprofile as bp

for profile in bp.list_profiles():           # or bp.list_profiles("chrome")
    print(profile.label, profile.path)
    for h in bp.extract_history(profile):
        print(h.last_visit, h.visit_count, h.url)

    cookies = bp.extract_cookies(profile, keyring="GNOMEKEYRING")
    logins  = bp.extract_logins(profile, keyring="GNOMEKEYRING")
```

Every extractor takes a `Profile` and returns a list of dataclass records
(`Cookie`, `HistoryEntry`, `Bookmark`, `AutofillEntry`, `Login`, `CreditCard`);
each has `.to_dict()` for JSON serialization. Records keep raw structured fields
(domains, paths, secure/httponly/samesite flags, decrypted values) so downstream
consumers can replay them — see `TODO.pydoll-integration.md`.

## Platform support

Profile locations and decryption are implemented for Linux, macOS and Windows
(ported from yt-dlp). Only **Linux** has been tested in this environment; the
macOS Keychain and Windows DPAPI paths are carried over unverified.

## Project Layout

```
src/browserprofile/
  profiles.py        # browser detection + Profile enumeration (the dispatch hub)
  cookies.py         # cookie extraction (chromium decrypt / firefox plaintext)
  history.py         # browsing history
  bookmarks.py       # bookmarks (chromium JSON / firefox places.sqlite)
  autofill.py        # form autofill
  passwords.py       # saved logins + credit cards
  chromium_crypto.py # v10/v11 value decryptor hierarchy (ported)
  keyrings.py        # Linux keyring / macOS Keychain / Windows DPAPI (ported)
  firefox_crypto.py  # Firefox NSS key4.db + logins.json decryption (new)
  _aes.py            # AES / PBKDF2 primitives
  _paths.py          # profile-dir + SQLite copy-open helpers (ported)
  records.py         # dataclasses + timestamp conversions
  logger.py          # logging shim
  cli.py             # command-line interface
```

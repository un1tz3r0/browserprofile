# TODO: pydoll integration (future project)

Not part of `browserprofile` itself — a **separate** downstream project that
consumes `browserprofile` as a library. Recorded here so the extraction API is
designed to support it.

## Goal

A mixin for pydoll's browser/tab class (`/home/owner/prj/browserdata/pydoll`)
that loads **part or all** of a user's real browser profile data (extracted by
`browserprofile`) into pydoll's throwaway session profile. Result: pydoll can
seamlessly hit sites the user is already logged into — no re-authentication.

pydoll drives a real live browser with it's own window and tabs and everything
(which can be hidden for things like running on headless servers etc.). It uses
the Chrome DevTools Protocol (CDP) to communicate with the browser via an in-memory
local unix-domain socket, using a **temporary user profile (with `--user-data-dir`)** 
created upon each startup (see `pydoll/pydoll/browser/managers/temp_dir_manager.py`).

It has **no** profile-extraction code of its own — that is exactly the gap 
`browserprofile` seeks to fill with a proposed extension which would implement extracting
the user's persistent regular browser profile data and then injecting a copy of it into 
pydoll's ephemeral profile, to allow seamless interoperability when trasitioning from 
user-driven manual browsing to automated tool-/agent-directed browsing/scraping.

## Two injection strategies

1. **CDP live injection (preferred for cookies).**
   - Cookies: `Network.setCookie` / `Storage.setCookies` (pydoll already wraps
     these in `pydoll/pydoll/commands/network_commands.py` / `storage_commands.py`).
   - Map `browserprofile` `Cookie` records → CDP cookie params (name, value,
     domain, path, secure, httpOnly, expires, sameSite). **This is why `Cookie`
     records must carry the raw decrypted value + all flags, not just a Netscape
     dump.**

2. **Pre-seed the temp profile on disk (before launch).**
   - Write cookies/history/logins into the temp `--user-data-dir` SQLite files
     (`Cookies`, `History`, `Login Data`) *before* pydoll starts the browser.
   - Complication: Chromium re-encrypts cookie/login values with the *target*
     machine's OS key. Either (a) inject via CDP after launch (strategy 1), or
     (b) re-encrypt values for the temp profile's key. CDP path avoids this.

## API implications for `browserprofile` (honor these while building)

- Records must expose **raw structured fields**, not just export blobs:
  cookies keep domain/path/secure/expiry/value; logins keep url/username/password.
- Keep a clean `list_profiles()` → per-`Profile` extractor call flow so the mixin
  can let the user pick which browser/profile to import from.
- Selective import: allow extracting a **single domain / URL subset** of cookies
  (add a `host`/`domain` filter to `extract_cookies`) so the mixin can pull only
  what a target site needs.
- Cookie → CDP mapping helper could live in the mixin project, not here.

## Open questions

- `SameSite` and `httpOnly` are not in the Chromium `cookies` columns we currently
  read (`is_httponly`, `samesite` columns exist in the DB — add them if the mixin
  needs them for faithful CDP replay).
- Firefox → Chromium cookie domain/host format differences (leading-dot handling).

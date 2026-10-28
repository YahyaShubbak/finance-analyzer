# Security

## Reporting a vulnerability

Please report security problems **privately** through GitHub: open the
repository's **Security** tab and choose **Report a vulnerability**. Do not
open a public issue for them.

Never include real bank statements, account numbers, IBANs, names or a
database in a report. If a file is needed to reproduce the problem, make an
invented one with the same layout.

This is a hobby project: reports are answered as time allows, usually
within a few weeks.

## What the app protects — and what not

- It listens on `127.0.0.1` only and rejects requests from other websites
  (host check against DNS rebinding, a required header against cross-site
  requests). Setting `FINANCE_HOST` to another address exposes your data to
  the network — there is no login.
- Anyone who can use your user account on the computer can open the app and
  read the data folder. Use separate user accounts on a shared computer.
- Backups are ZIP files and are **not encrypted**.

Problems within these limits (e.g. another website reading or changing your
data, a crafted statement file that runs code or writes outside the data
folder) are vulnerabilities. Access by someone already logged in as you is
not.

## Supported versions

Only the latest release receives fixes.

# Security policy

plane-autojoin decides who gets into a Plane workspace without an invite,
so a bug in it can grant access. Please report anything that could let a
user join who should not, such as a bypass of the verified-email or domain
check, a way to obtain the Admin role, or a log line that leaks an email
address or row data.

## Reporting

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/miriel-ai/plane-autojoin/security/advisories/new)
for this repository. Please don't open a public issue. We aim to reply
within a week.

Vulnerabilities in Plane itself, including its OAuth providers and how it
sets `is_email_verified`, belong upstream: see
[Plane's security policy](https://github.com/makeplane/plane/security/policy).

## Supported versions

Only the latest release gets fixes.

## Design notes

- Only users Plane marked as verified can join, and bots never join. See
  "Which sign-ins count as verified" in the README.
- Domains match exactly: no subdomains and no wildcards. Admitting every
  verified email takes an explicit
  `PLANE_AUTOJOIN_TRUST_ALL_VERIFIED_EMAILS=true`, and in that mode joins
  are skipped while Plane's password or magic-code login is enabled.
- The Admin role cannot be configured, and an existing membership is never
  changed.
- Invalid configuration turns the app off rather than guessing.
- Logs carry user ids and exception class names only.

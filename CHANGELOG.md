# Changelog

## 0.1.0

First release. Tested with Plane CE v1.4.2.

- New users with a verified email join one or more workspaces on creation,
  with the Member or Guest role.
- Eligibility comes from an exact email-domain allowlist
  (`PLANE_AUTOJOIN_EMAIL_DOMAINS`) or, as an explicit opt-in for IdP-gated
  setups, any verified email (`PLANE_AUTOJOIN_TRUST_ALL_VERIFIED_EMAILS`).
  The opt-in is refused while password or magic-code login is enabled.
- Published as a GitHub Release (sdist, wheel and `SHA256SUMS`) for
  mounting into Plane's backend containers.

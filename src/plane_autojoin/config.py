"""Configuration from the environment, read once at start-up.

PLANE_AUTOJOIN_WORKSPACE_SLUG
    The workspace to join, or several, comma-separated. The first one
    that exists becomes the user's landing workspace. Unset: the app
    does nothing.
PLANE_AUTOJOIN_EMAIL_DOMAINS
    Comma-separated email domains, exact match (no subdomains).
PLANE_AUTOJOIN_TRUST_ALL_VERIFIED_EMAILS
    "true" to join every new user with a verified email, whatever the
    domain. Only for setups where the identity provider is the only way
    to create accounts and already decides who may sign in. Exactly one
    of this and PLANE_AUTOJOIN_EMAIL_DOMAINS must be set.
PLANE_AUTOJOIN_ROLE
    "member" / 15 (the default) or "guest" / 5. Admin (20) is refused.
"""

import re
from dataclasses import dataclass

PREFIX = "PLANE_AUTOJOIN_"
WORKSPACE_SLUG = PREFIX + "WORKSPACE_SLUG"
EMAIL_DOMAINS = PREFIX + "EMAIL_DOMAINS"
TRUST_ALL = PREFIX + "TRUST_ALL_VERIFIED_EMAILS"
ROLE = PREFIX + "ROLE"

# Plane's ROLE_CHOICES (plane/db/models/workspace.py): 20 Admin, 15 Member,
# 5 Guest. Admin is deliberately not on the list.
MEMBER, GUEST = 15, 5
ROLES = {"": MEMBER, "member": MEMBER, "15": MEMBER, "guest": GUEST, "5": GUEST}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}

# One DNS label, then more after dots. Lower-case ASCII: IDNs in punycode.
_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$")


class ConfigError(ValueError):
    """The variables are set but invalid. Messages name variables, never values
    that could be secret (none of these are, but keep it that way)."""


@dataclass(frozen=True)
class Config:
    workspace_slugs: tuple[str, ...]
    email_domains: frozenset[str]
    trust_all_verified: bool
    role: int

    def allows(self, email):
        """Whether an (already verified) email qualifies."""
        local, sep, domain = (email or "").strip().lower().rpartition("@")
        if not (local and sep and domain):
            return False
        return self.trust_all_verified or domain in self.email_domains


def _split(value):
    seen = []
    for item in (value or "").split(","):
        item = item.strip()
        if item and item not in seen:
            seen.append(item)
    return seen


def load(environ):
    """Return a Config, or None when auto-join is not configured (no slug).
    Raise ConfigError when it is configured but invalid."""
    # Kept as given: Plane's slugs may contain upper-case letters and are
    # matched exactly.
    slugs = tuple(_split(environ.get(WORKSPACE_SLUG)))
    if not slugs:
        return None

    domains = set()
    for d in _split(environ.get(EMAIL_DOMAINS)):
        d = d.lower().removeprefix("@")
        if "*" in d:
            raise ConfigError(f"{EMAIL_DOMAINS} takes exact domains, no wildcards; to allow any domain see {TRUST_ALL}")
        if not _DOMAIN.match(d):
            raise ConfigError(f"{EMAIL_DOMAINS} has an entry that is not a domain name")
        domains.add(d)

    trust_raw = (environ.get(TRUST_ALL) or "").strip().lower()
    if trust_raw in _TRUE:
        trust_all = True
    elif trust_raw in _FALSE:
        trust_all = False
    else:
        raise ConfigError(f"{TRUST_ALL} must be true or false")

    if trust_all and domains:
        raise ConfigError(f"set {EMAIL_DOMAINS} or {TRUST_ALL}, not both")
    if not trust_all and not domains:
        raise ConfigError(f"{WORKSPACE_SLUG} is set but neither {EMAIL_DOMAINS} nor {TRUST_ALL} is")

    role_raw = (environ.get(ROLE) or "").strip().lower()
    if role_raw not in ROLES:
        raise ConfigError(f"{ROLE} must be member (15) or guest (5); admin is refused")

    return Config(
        workspace_slugs=slugs,
        email_domains=frozenset(domains),
        trust_all_verified=trust_all,
        role=ROLES[role_raw],
    )

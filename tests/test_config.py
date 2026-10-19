import pytest

from plane_autojoin.config import GUEST, MEMBER, ConfigError, load


def env(**kw):
    return {f"PLANE_AUTOJOIN_{k.upper()}": v for k, v in kw.items()}


def test_unset_is_off():
    assert load({}) is None
    assert load(env(workspace_slug=" , ")) is None
    # Domains without a workspace: still off, nothing to join.
    assert load(env(email_domains="example.com")) is None


def test_domains():
    cfg = load(env(workspace_slug="acme", email_domains=" Example.com, @example.org ,example.com"))
    assert cfg.workspace_slugs == ("acme",)
    assert cfg.email_domains == {"example.com", "example.org"}
    assert cfg.trust_all_verified is False
    assert cfg.role == MEMBER


def test_several_workspaces_keep_their_order():
    cfg = load(env(workspace_slug="b, a ,b", email_domains="example.com"))
    assert cfg.workspace_slugs == ("b", "a")


@pytest.mark.parametrize("value", ["member", "Member", "15", " 15 ", ""])
def test_role_member(value):
    assert load(env(workspace_slug="acme", email_domains="example.com", role=value)).role == MEMBER


@pytest.mark.parametrize("value", ["guest", "5"])
def test_role_guest(value):
    assert load(env(workspace_slug="acme", email_domains="example.com", role=value)).role == GUEST


@pytest.mark.parametrize("value", ["20", "admin", "owner", "10", "x"])
def test_role_refused(value):
    with pytest.raises(ConfigError, match="admin is refused"):
        load(env(workspace_slug="acme", email_domains="example.com", role=value))


def test_needs_domains_or_trust_all():
    with pytest.raises(ConfigError, match="neither"):
        load(env(workspace_slug="acme"))
    with pytest.raises(ConfigError, match="neither"):
        load(env(workspace_slug="acme", trust_all_verified_emails="false"))


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_trust_all(value):
    cfg = load(env(workspace_slug="acme", trust_all_verified_emails=value))
    assert cfg.trust_all_verified is True
    assert cfg.email_domains == frozenset()


def test_trust_all_and_domains_refused():
    with pytest.raises(ConfigError, match="not both"):
        load(env(workspace_slug="acme", email_domains="example.com", trust_all_verified_emails="true"))


def test_trust_all_garbage_refused():
    with pytest.raises(ConfigError, match="true or false"):
        load(env(workspace_slug="acme", email_domains="example.com", trust_all_verified_emails="maybe"))


@pytest.mark.parametrize("value", ["*", "*.example.com", "example.com,*"])
def test_wildcards_refused(value):
    with pytest.raises(ConfigError, match="no wildcards"):
        load(env(workspace_slug="acme", email_domains=value))


@pytest.mark.parametrize("value", ["exa mple.com", "user@example.com", "example..com", "-example.com", "example.com."])
def test_bad_domain_refused(value):
    with pytest.raises(ConfigError, match="not a domain name"):
        load(env(workspace_slug="acme", email_domains=value))


def test_allows_exact_domain_only():
    cfg = load(env(workspace_slug="acme", email_domains="example.com"))
    assert cfg.allows("a@example.com")
    assert cfg.allows(" A@Example.COM ")
    assert not cfg.allows("a@sub.example.com")
    assert not cfg.allows("a@example.com.evil.test")
    assert not cfg.allows("a@other.test")
    assert not cfg.allows("@example.com")
    assert not cfg.allows("example.com")
    assert not cfg.allows("")
    assert not cfg.allows(None)


def test_allows_any_domain_in_trust_all():
    cfg = load(env(workspace_slug="acme", trust_all_verified_emails="true"))
    assert cfg.allows("a@gmail.example")
    assert not cfg.allows("no-at-sign")
    assert not cfg.allows("a@")


def test_slug_case_is_kept():
    # Plane accepts upper-case slugs and matches them exactly.
    assert load(env(workspace_slug="Acme", email_domains="example.com")).workspace_slugs == ("Acme",)

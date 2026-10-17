import logging

import pytest
from django.db import transaction
from plane.db.models import Profile, User, Workspace, WorkspaceMember
from plane.license.utils import instance_value
from plane.utils import cache

from plane_autojoin import receivers

from .conftest import sign_up

# Plane serves requests in autocommit, where on_commit callbacks run at once:
# transaction=True gives the tests the same behaviour.
autocommit = pytest.mark.django_db(transaction=True)


def members(user):
    return list(WorkspaceMember.objects.filter(member=user).values_list("workspace__slug", "role", "is_active"))


@autocommit
def test_allowed_domain_joins(autojoin, workspace):
    autojoin(workspace_slug="acme", email_domains="example.com")
    user, profile = sign_up("new@example.com")

    assert members(user) == [("acme", 15, True)]
    assert cache.calls == [
        {"path": "/api/workspaces/acme/members/", "url_params": False, "user": False, "multiple": True}
    ]
    profile.refresh_from_db()
    assert profile.last_workspace_id == workspace.id
    assert profile.onboarding_step["workspace_join"] is True
    # The rest of onboarding is left to Plane.
    assert profile.onboarding_step["profile_complete"] is False
    assert profile.is_onboarded is False


@autocommit
def test_profile_instance_held_by_caller_is_current(autojoin, workspace):
    # Plane keeps using the Profile it created; it must not hold stale values.
    autojoin(workspace_slug="acme", email_domains="example.com")
    _, profile = sign_up("new@example.com")
    assert profile.last_workspace_id == workspace.id


@autocommit
def test_other_domain_does_not_join(autojoin, workspace):
    autojoin(workspace_slug="acme", email_domains="example.com")
    for email in ["new@other.test", "new@sub.example.com", "new@example.com.other.test"]:
        user, profile = sign_up(email)
        assert members(user) == []
        profile.refresh_from_db()
        assert profile.last_workspace_id is None
    assert cache.calls == []


@autocommit
def test_unverified_email_does_not_join(autojoin, workspace):
    autojoin(workspace_slug="acme", email_domains="example.com")
    user, profile = sign_up("new@example.com", verified=False)
    assert members(user) == []
    profile.refresh_from_db()
    assert profile.last_workspace_id is None
    assert profile.onboarding_step["workspace_join"] is False


@autocommit
def test_bot_does_not_join(autojoin, workspace):
    autojoin(workspace_slug="acme", email_domains="example.com")
    user, _ = sign_up("bot@example.com", bot=True)
    assert members(user) == []


@autocommit
def test_existing_user_saved_again_does_not_join(autojoin, workspace):
    user, _ = sign_up("old@example.com")
    autojoin(workspace_slug="acme", email_domains="example.com")
    user.save()
    assert members(user) == []


@autocommit
def test_rerun_is_idempotent(autojoin, workspace):
    cfg = autojoin(workspace_slug="acme", email_domains="example.com")
    user, profile = sign_up("new@example.com")
    receivers.join(user.pk, cfg)
    receivers.join(user.pk, cfg)
    assert members(user) == [("acme", 15, True)]
    assert len(cache.calls) == 1
    profile.refresh_from_db()
    assert profile.last_workspace_id == workspace.id


@autocommit
def test_existing_membership_role_is_kept(autojoin, workspace):
    cfg = autojoin(workspace_slug="acme", email_domains="example.com", role="guest")
    user = User.objects.create(email="x@other.test", is_email_verified=True)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=20)
    receivers.join(user.pk, cfg)
    assert members(user) == [("acme", 20, True)]


@autocommit
def test_guest_role(autojoin, workspace):
    autojoin(workspace_slug="acme", email_domains="example.com", role="guest")
    user, _ = sign_up("new@example.com")
    assert members(user) == [("acme", 5, True)]


@autocommit
def test_existing_last_workspace_is_kept(autojoin, workspace):
    cfg = autojoin(workspace_slug="acme", email_domains="example.com")
    other = Workspace.objects.create(slug="other")
    user = User.objects.create(email="x@other.test", is_email_verified=True)
    profile = Profile.objects.create(user=user, last_workspace_id=other.id)
    receivers.join(user.pk, cfg)
    profile.refresh_from_db()
    assert profile.last_workspace_id == other.id
    assert profile.onboarding_step["workspace_join"] is True


@pytest.mark.django_db
def test_outer_transaction_joins_after_commit(autojoin, workspace, django_capture_on_commit_callbacks):
    # Under an outer transaction the join waits for the commit; the Profile
    # exists by then and the join updates it itself.
    autojoin(workspace_slug="acme", email_domains="example.com")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with transaction.atomic():
            user, profile = sign_up("new@example.com")
            assert members(user) == []
    assert len(callbacks) == 1
    assert members(user) == [("acme", 15, True)]
    profile.refresh_from_db()
    assert profile.last_workspace_id == workspace.id
    assert profile.onboarding_step["workspace_join"] is True


@autocommit
def test_several_workspaces(autojoin, db):
    first = Workspace.objects.create(slug="first")
    Workspace.objects.create(slug="second")
    autojoin(workspace_slug="missing,first,second", email_domains="example.com")
    user, profile = sign_up("new@example.com")
    assert sorted(members(user)) == [("first", 15, True), ("second", 15, True)]
    profile.refresh_from_db()
    # The first listed workspace that exists is the landing one.
    assert profile.last_workspace_id == first.id


@autocommit
def test_profile_receiver_follows_listed_order(autojoin, db):
    # The profile receiver picks the landing workspace by the listed order,
    # not by whichever membership the database returns first.
    first = Workspace.objects.create(slug="first")
    second = Workspace.objects.create(slug="second")
    autojoin(workspace_slug="first,second", email_domains="example.com")
    user = User.objects.create(email="x@other.test", is_email_verified=True)
    WorkspaceMember.objects.create(workspace=second, member=user, role=15)
    WorkspaceMember.objects.create(workspace=first, member=user, role=15)
    profile = Profile.objects.create(user=user)
    profile.refresh_from_db()
    assert profile.last_workspace_id == first.id


@autocommit
def test_missing_workspace_logs_and_does_not_break_sign_up(autojoin, db, caplog):
    autojoin(workspace_slug="acme", email_domains="example.com")
    with caplog.at_level(logging.INFO, logger="plane_autojoin"):
        user, _ = sign_up("new@example.com")
    assert members(user) == []
    assert "workspace acme not found" in caplog.text


@autocommit
def test_errors_are_logged_without_email(autojoin, workspace, caplog, monkeypatch):
    autojoin(workspace_slug="acme", email_domains="example.com")

    def boom(*a, **kw):
        raise RuntimeError("secret row value new@example.com")

    monkeypatch.setattr(WorkspaceMember.objects, "get_or_create", boom)
    with caplog.at_level(logging.INFO, logger="plane_autojoin"):
        user, _ = sign_up("new@example.com")
    assert User.objects.filter(pk=user.pk).exists()
    assert f"user {user.pk} not joined to acme (RuntimeError)" in caplog.text
    assert "example.com" not in caplog.text


@autocommit
def test_trust_all_joins_any_verified_domain(autojoin, workspace, sso_only):
    autojoin(workspace_slug="acme", trust_all_verified_emails="true")
    user, profile = sign_up("someone@consumer-mail.test")
    assert members(user) == [("acme", 15, True)]
    profile.refresh_from_db()
    assert profile.last_workspace_id == workspace.id


@autocommit
def test_trust_all_still_needs_verified_email(autojoin, workspace, sso_only):
    autojoin(workspace_slug="acme", trust_all_verified_emails="true")
    user, _ = sign_up("someone@consumer-mail.test", verified=False)
    assert members(user) == []


@autocommit
@pytest.mark.parametrize(
    "values",
    [
        {},  # Plane's defaults: both on
        {"ENABLE_EMAIL_PASSWORD": "1", "ENABLE_MAGIC_LINK_LOGIN": "0"},
        {"ENABLE_EMAIL_PASSWORD": "0", "ENABLE_MAGIC_LINK_LOGIN": "1"},
    ],
)
def test_trust_all_skipped_while_other_sign_in_is_on(autojoin, workspace, caplog, monkeypatch, values):
    monkeypatch.delenv("ENABLE_EMAIL_PASSWORD", raising=False)
    monkeypatch.delenv("ENABLE_MAGIC_LINK_LOGIN", raising=False)
    autojoin(workspace_slug="acme", trust_all_verified_emails="true")
    instance_value.values.update(values)
    with caplog.at_level(logging.INFO, logger="plane_autojoin"):
        user, _ = sign_up("someone@consumer-mail.test")
    assert members(user) == []
    assert "needs ENABLE_EMAIL_PASSWORD=0 and ENABLE_MAGIC_LINK_LOGIN=0" in caplog.text


@autocommit
def test_trust_all_fails_closed_when_config_unreadable(autojoin, workspace, sso_only):
    autojoin(workspace_slug="acme", trust_all_verified_emails="true")
    instance_value.fail = True
    user, _ = sign_up("someone@consumer-mail.test")
    assert members(user) == []


@autocommit
def test_domain_mode_ignores_other_sign_in_settings(autojoin, workspace):
    # A magic code proves mailbox ownership, which is what a domain check needs.
    autojoin(workspace_slug="acme", email_domains="example.com")
    instance_value.values.update({"ENABLE_EMAIL_PASSWORD": "1", "ENABLE_MAGIC_LINK_LOGIN": "1"})
    user, _ = sign_up("new@example.com")
    assert members(user) == [("acme", 15, True)]


def test_invalid_config_disables_and_logs(autojoin, caplog):
    with caplog.at_level(logging.INFO, logger="plane_autojoin"):
        assert autojoin(workspace_slug="acme", email_domains="example.com", role="20") is None
    assert receivers.CONFIG is None
    assert "auto-join disabled" in caplog.text


def test_unset_connects_nothing(autojoin):
    assert autojoin() is None
    assert receivers.CONFIG is None


def test_trust_all_logs_a_warning(autojoin, caplog):
    with caplog.at_level(logging.INFO, logger="plane_autojoin"):
        autojoin(workspace_slug="acme", trust_all_verified_emails="true")
    assert any(r.levelno == logging.WARNING and "TRUST_ALL_VERIFIED_EMAILS is on" in r.message for r in caplog.records)

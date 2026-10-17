# Fed to `python manage.py shell` inside Plane's backend image by run.sh.
# Users are created through Plane's own sign-up code
# (Adapter.complete_login_or_signup), so the same code path and signals run
# as for a real OAuth, magic-code or password sign-up. Exits non-zero on the
# first failed check.
import os
import sys
import uuid

from django.apps import apps
from django.test import RequestFactory
from plane.authentication.adapter.base import Adapter
from plane.db.models import Profile, User, UserNotificationPreference, Workspace, WorkspaceMember

from plane_autojoin import receivers

SCENARIO = os.environ["SCENARIO"]
failures = []


def check(ok, what):
    print(("  ok    " if ok else "  FAIL  ") + what)
    if not ok:
        failures.append(what)


def sign_up(email, verified=True):
    """verified=True is what Plane's OAuth providers and magic codes pass
    (is_password_autoset), and is what sets is_email_verified; False is a
    password sign-up."""
    adapter = Adapter(request=RequestFactory().get("/", HTTP_USER_AGENT="plane-autojoin-it"), provider="google")
    adapter.user_data = {
        "email": email,
        "user": {"is_password_autoset": verified, "first_name": "Test", "last_name": "User", "avatar": ""},
    }
    if not verified:
        adapter.code = "Integration-Test-Passphrase-" + uuid.uuid4().hex
    return adapter.complete_login_or_signup()


def make_workspace(slug):
    owner = User.objects.create(email=f"owner-{slug}@owner.test", username=uuid.uuid4().hex)
    return Workspace.objects.create(name=slug, slug=slug, owner=owner)


def memberships(user):
    return list(WorkspaceMember.objects.filter(member=user).values_list("workspace__slug", "role", "is_active"))


def joined(user, workspace, role=15):
    profile = Profile.objects.get(user=user)
    check(memberships(user) == [(workspace.slug, role, True)], f"{user.email}: member of {workspace.slug} as {role}")
    check(profile.last_workspace_id == workspace.id, f"{user.email}: profile.last_workspace_id is {workspace.slug}")
    check(profile.onboarding_step.get("workspace_join") is True, f"{user.email}: onboarding_step.workspace_join")
    check(profile.is_onboarded is False, f"{user.email}: onboarding left to Plane")


def not_joined(user):
    profile = Profile.objects.get(user=user)
    check(memberships(user) == [], f"{user.email}: no membership")
    check(profile.last_workspace_id is None, f"{user.email}: profile untouched")


check(apps.is_installed("plane_autojoin"), "plane_autojoin is installed")

if SCENARIO == "domains":
    check(receivers.CONFIG is not None, "auto-join is on")
    ws = make_workspace("acme")

    alice = sign_up("alice@example.com")
    check(alice.is_email_verified, "OAuth-style sign-up is verified")
    joined(alice, ws)
    check(UserNotificationPreference.objects.filter(user=alice).exists(), "Plane's own User receiver still ran")

    not_joined(sign_up("bob@example.org"))
    not_joined(sign_up("bob@sub.example.com"))

    carol = sign_up("carol@example.com", verified=False)
    check(not carol.is_email_verified, "password sign-up is not verified")
    not_joined(carol)

    # Idempotent: a second sign-in and repeated joins leave one membership.
    sign_up("alice@example.com")
    receivers.join(alice.pk)
    receivers.join(alice.pk)
    joined(alice, ws)

elif SCENARIO == "trust_all":
    check(receivers.CONFIG is not None and receivers.CONFIG.trust_all_verified, "trust-all mode is on")
    ws = make_workspace("lab")
    joined(sign_up("dave@consumer-mail.test"), ws)
    not_joined(sign_up("erin@consumer-mail.test", verified=False))

elif SCENARIO == "trust_all_magic_code_on":
    make_workspace("lab2")
    not_joined(sign_up("frank@consumer-mail.test"))

elif SCENARIO == "off":
    check(receivers.CONFIG is None, "auto-join is off without PLANE_AUTOJOIN_*")
    make_workspace("quiet")
    not_joined(sign_up("grace@example.com"))

else:
    failures.append(f"unknown scenario {SCENARIO}")

if failures:
    print(f"{len(failures)} check(s) failed")
    sys.exit(1)

import pytest
from plane.db.models import Profile, User, Workspace
from plane.license.utils import instance_value
from plane.utils import cache

from plane_autojoin import receivers


@pytest.fixture
def autojoin():
    """connect(**env) turns auto-join on with those PLANE_AUTOJOIN_* values
    (keys without the prefix); it is turned off again after the test."""

    def connect(**env):
        return receivers.connect({f"PLANE_AUTOJOIN_{k.upper()}": v for k, v in env.items()})

    cache.calls.clear()
    instance_value.values.clear()
    instance_value.fail = False
    yield connect
    receivers.disconnect()
    cache.calls.clear()
    instance_value.values.clear()
    instance_value.fail = False


@pytest.fixture
def sso_only():
    """Plane's instance config with password and magic-code login off."""
    instance_value.values.update({"ENABLE_EMAIL_PASSWORD": "0", "ENABLE_MAGIC_LINK_LOGIN": "0"})


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(slug="acme")


def sign_up(email, verified=True, bot=False):
    """The order of Plane's Adapter.complete_login_or_signup: save the User
    (post_save fires), then create the Profile."""
    user = User(email=email, is_email_verified=verified, is_bot=bot)
    user.save()
    profile = Profile.objects.create(user=user)
    return user, profile

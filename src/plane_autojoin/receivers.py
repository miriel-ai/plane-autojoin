"""The two post_save receivers that do the auto-join.

Written against Plane CE v1.4.2. Re-check the files named here when
upgrading Plane.

What a join does is what accepting a workspace invite does
(plane/app/views/workspace/invite.py WorkspaceJoinEndpoint, and
plane/authentication/utils/workspace_project_join.py on sign-in):
  - a WorkspaceMember row with the configured role (get_or_create, so it is
    idempotent);
  - the workspace's cached member list invalidated;
  - the profile's last_workspace_id pointed at the workspace, plus
    onboarding_step.workspace_join. (Upstream's WorkspaceJoinEndpoint sets
    user.last_workspace_id, a field User does not have, so it is lost; the
    field Plane reads is on Profile.)
Not copied: the analytics event (track_event), and projects, because
accepting a workspace invite joins none. Onboarding is left to Plane: the
user still gets the profile step, which then finishes into the workspace.

Ordering. Plane's sign-up (plane/authentication/adapter/base.py,
complete_login_or_signup) saves the User, which fires post_save, and only
then creates the Profile. Requests run in autocommit (no ATOMIC_REQUESTS),
so transaction.on_commit runs the join at once, before the Profile exists;
the Profile receiver then points the new profile at the workspace. Under an
outer transaction, on_commit waits for the commit, the Profile exists by
then, and the join updates it directly. Either way both halves happen once.

Never breaks sign-up: every receiver catches and logs its own errors, and
logs the user id and the exception class only (no email, no exception
text, which can carry row values).
"""

import functools
import logging
import os

from django.db import transaction
from django.db.models.signals import post_save

from . import config as config_module

logger = logging.getLogger("plane_autojoin")

USER_UID = "plane_autojoin.user"
PROFILE_UID = "plane_autojoin.profile"

# Set by connect(); None while auto-join is off.
CONFIG = None


def connect(environ=None):
    """Read the configuration and connect the receivers. Returns the Config,
    or None when auto-join stays off."""
    global CONFIG
    try:
        cfg = config_module.load(os.environ if environ is None else environ)
    except config_module.ConfigError as e:
        logger.error("auto-join disabled: %s", e)
        return None
    if cfg is None:
        return None

    from plane.db.models import Profile, User

    CONFIG = cfg
    post_save.connect(on_user_saved, sender=User, dispatch_uid=USER_UID)
    post_save.connect(on_profile_saved, sender=Profile, dispatch_uid=PROFILE_UID)
    if cfg.trust_all_verified:
        logger.warning(
            "auto-join: %s is on: every new user with a verified email joins %s. "
            "Joins are skipped while password or magic-code login is enabled.",
            config_module.TRUST_ALL,
            ",".join(cfg.workspace_slugs),
        )
    else:
        logger.info("auto-join: on for %s", ",".join(cfg.workspace_slugs))
    return cfg


def disconnect():
    """Undo connect(). For tests."""
    global CONFIG
    from plane.db.models import Profile, User

    post_save.disconnect(sender=User, dispatch_uid=USER_UID)
    post_save.disconnect(sender=Profile, dispatch_uid=PROFILE_UID)
    CONFIG = None


def eligible(user, cfg):
    # Only addresses Plane has verified: OAuth sign-ups and magic codes set
    # is_email_verified, password sign-ups do not. Bots (the workspace-seed
    # bot) never join.
    if user.is_bot or not user.is_email_verified:
        return False
    return cfg.allows(user.email)


def on_user_saved(sender, instance, created, raw=False, **kwargs):
    cfg = CONFIG
    if not created or raw or cfg is None:
        return
    try:
        if eligible(instance, cfg):
            transaction.on_commit(functools.partial(join, instance.pk, cfg))
    except Exception as e:
        logger.error("auto-join: user %s not joined (%s)", instance.pk, type(e).__name__)


def other_sign_in_enabled():
    """Whether password or magic-code login is on in Plane's instance config.
    Defaults mirror Plane's own (both on unless configured off); any error
    counts as on, so trust-all mode fails closed."""
    try:
        from plane.license.utils.instance_value import get_configuration_value

        password, magic = get_configuration_value(
            [
                {"key": "ENABLE_EMAIL_PASSWORD", "default": os.environ.get("ENABLE_EMAIL_PASSWORD", "1")},
                {"key": "ENABLE_MAGIC_LINK_LOGIN", "default": os.environ.get("ENABLE_MAGIC_LINK_LOGIN", "1")},
            ]
        )
    except Exception as e:
        logger.error("auto-join: could not read Plane's sign-in settings (%s)", type(e).__name__)
        return True
    return str(password) != "0" or str(magic) != "0"


def join(user_id, cfg=None):
    cfg = cfg or CONFIG
    if cfg is None:
        return
    try:
        if cfg.trust_all_verified and other_sign_in_enabled():
            # A magic code proves only that someone reads the mailbox, not
            # that the identity provider let them in.
            logger.error(
                "auto-join: user %s not joined: %s needs ENABLE_EMAIL_PASSWORD=0 and ENABLE_MAGIC_LINK_LOGIN=0",
                user_id,
                config_module.TRUST_ALL,
            )
            return

        from plane.db.models import Profile, Workspace, WorkspaceMember
        from plane.utils.cache import invalidate_cache_directly
    except Exception as e:
        logger.error("auto-join: user %s not joined (%s)", user_id, type(e).__name__)
        return

    landing = None
    for slug in cfg.workspace_slugs:
        try:
            # A savepoint per workspace, so one failure cannot leave the
            # connection unusable for the next (join() normally runs in
            # autocommit, from on_commit).
            with transaction.atomic():
                workspace = Workspace.objects.filter(slug=slug).first()
                if workspace is None:
                    logger.error("auto-join: workspace %s not found; user %s not joined to it", slug, user_id)
                    continue
                _, created = WorkspaceMember.objects.get_or_create(
                    workspace=workspace, member_id=user_id, defaults={"role": cfg.role}
                )
        except Exception as e:
            logger.error("auto-join: user %s not joined to %s (%s)", user_id, slug, type(e).__name__)
            continue

        # The membership exists from here on: it is the landing workspace
        # even if clearing the cache below fails.
        if landing is None:
            landing = workspace.id
        if created:
            logger.info("auto-join: user %s joined %s as role %s", user_id, workspace.slug, cfg.role)
            try:
                # As workspace_project_join.py does after adding members.
                invalidate_cache_directly(
                    path=f"/api/workspaces/{workspace.slug}/members/", url_params=False, user=False, multiple=True
                )
            except Exception as e:
                logger.error("auto-join: members cache of %s not cleared (%s)", workspace.slug, type(e).__name__)

    if landing is None:
        return
    try:
        # See on_profile_saved.
        with transaction.atomic():
            profile = Profile.objects.filter(user_id=user_id).first()
            if profile is not None:
                point_profile(profile, landing)
    except Exception as e:
        logger.error("auto-join: profile of user %s not updated (%s)", user_id, type(e).__name__)


def on_profile_saved(sender, instance, created, raw=False, **kwargs):
    cfg = CONFIG
    if not created or raw or cfg is None or instance.last_workspace_id is not None:
        return
    try:
        from plane.db.models import WorkspaceMember

        # A savepoint: this runs inside Plane's own transaction when there is
        # one, and a database error caught without it would leave that
        # transaction unusable for the rest of the sign-up.
        with transaction.atomic():
            joined = dict(
                WorkspaceMember.objects.filter(
                    workspace__slug__in=cfg.workspace_slugs, member_id=instance.user_id, is_active=True
                ).values_list("workspace__slug", "workspace_id")
            )
            landing = next((joined[s] for s in cfg.workspace_slugs if s in joined), None)
            if landing is not None:
                point_profile(instance, landing)
    except Exception as e:
        logger.error("auto-join: profile of user %s not updated (%s)", instance.user_id, type(e).__name__)


def point_profile(profile, workspace_id):
    # Saves the instance the caller holds, so Plane's own copy (the adapter's
    # Profile.objects.create result) stays current. It is a save with
    # created=False, so on_profile_saved ignores it. A last_workspace_id
    # that is already set is kept.
    step = profile.onboarding_step or {}
    if profile.last_workspace_id is not None and step.get("workspace_join"):
        return
    if profile.last_workspace_id is None:
        profile.last_workspace_id = workspace_id
    profile.onboarding_step = {**step, "workspace_join": True}
    profile.save(update_fields=["last_workspace_id", "onboarding_step", "updated_at"])

import uuid

from django.db import models


def get_default_onboarding():
    return {
        "profile_complete": False,
        "workspace_create": False,
        "workspace_invite": False,
        "workspace_join": False,
    }


class User(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    email = models.CharField(max_length=255, unique=True, null=True)
    is_bot = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)


class Profile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    last_workspace_id = models.UUIDField(null=True)
    onboarding_step = models.JSONField(default=get_default_onboarding)
    is_onboarded = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    slug = models.SlugField(max_length=48, unique=True)


class WorkspaceMember(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="workspace_member")
    member = models.ForeignKey(User, on_delete=models.CASCADE, related_name="member_workspace")
    role = models.PositiveSmallIntegerField(default=5)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ["workspace", "member"]

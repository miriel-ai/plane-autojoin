# plane-autojoin

Auto-join for self-hosted [Plane](https://github.com/makeplane/plane)
Community Edition. A new user whose email is verified becomes a member of
your workspace the moment the account is created, the same as if they had
accepted an invite. You choose which users qualify: an allowlist of email
domains, or, for setups where the identity provider already decides who may
sign in, every verified email.

Plane CE has no domain auto-join. With sign-up open, a new colleague lands
on "create a workspace" and someone has to invite them by hand. This fixes
that without patching Plane or rebuilding its image: it is a small Django
app that you mount into Plane's backend containers and add to
`INSTALLED_APPS`.

> **Status:** tested against Plane CE **v1.4.2** only (see
> [Compatibility](#compatibility)).

## What it does

When Plane creates a user, two `post_save` receivers do what accepting a
workspace invite does:

- add a `WorkspaceMember` row with the configured role (`get_or_create`, so
  running it twice changes nothing);
- clear the workspace's cached member list;
- point the profile's `last_workspace_id` at the workspace and set
  `onboarding_step.workspace_join`, so the web app opens the workspace.

The user qualifies only if all of these hold:

- they are not a bot (Plane's workspace-seed bot never joins);
- Plane marked their email verified (`is_email_verified`, see
  [Which sign-ins count as verified](#which-sign-ins-count-as-verified));
- their email's domain is in `PLANE_AUTOJOIN_EMAIL_DOMAINS` (exact match,
  no subdomains), or `PLANE_AUTOJOIN_TRUST_ALL_VERIFIED_EMAILS` is on.

Onboarding is left to Plane: the user still gets the profile step (name,
avatar), which then finishes into the workspace. No projects are joined, as
with an invite; public projects are one "Join" click away. Existing users
are never touched: it runs only when an account is created.

It never breaks a sign-up. Every receiver catches and logs its own errors,
and logs the user id and the exception class only: no email addresses and
no exception text, which can carry row values.

## Install (docker compose)

1. **Get the code.** Download the release's sdist and checksum file, verify
   it, and unpack the package directory (`tar` is all you need):

   ```sh
   VERSION=0.1.0
   BASE=https://github.com/miriel-ai/plane-autojoin/releases/download/v$VERSION
   curl -fsSLO "$BASE/plane_autojoin-$VERSION.tar.gz"
   curl -fsSLO "$BASE/SHA256SUMS"
   sha256sum --check --ignore-missing SHA256SUMS
   tar -xzf "plane_autojoin-$VERSION.tar.gz" --strip-components=2 \
       "plane_autojoin-$VERSION/src/plane_autojoin"
   # -> ./plane_autojoin/
   ```

   For production, pin the checksum in your own deploy script rather than
   trusting the downloaded `SHA256SUMS`. The wheel works too: it is a zip
   file with `plane_autojoin/` at the top level.

2. **Add a settings module** next to your compose file, e.g.
   `plane_settings.py`. It is Plane's production settings plus this app and
   its logger:

   ```python
   from .production import *  # noqa: F403

   INSTALLED_APPS = [*INSTALLED_APPS, "plane_autojoin"]  # noqa: F405

   # Plane's LOGGING has no root handler: list the logger, or only
   # warnings reach the console, without Plane's JSON format.
   LOGGING["loggers"]["plane_autojoin"] = {  # noqa: F405
       "level": "INFO",
       "handlers": ["console"],
       "propagate": False,
   }
   ```

3. **Mount both into every backend container** (`api`, `worker`,
   `beat-worker`, `migrator`: they share one image and one settings
   module), point `DJANGO_SETTINGS_MODULE` at the settings module, and
   configure the app:

   ```yaml
   x-backend: &backend
     image: makeplane/plane-backend:v1.4.2
     environment:
       DJANGO_SETTINGS_MODULE: plane.settings.local_autojoin
       PLANE_AUTOJOIN_WORKSPACE_SLUG: acme
       PLANE_AUTOJOIN_EMAIL_DOMAINS: example.com
     volumes:
       - ./plane_settings.py:/code/plane/settings/local_autojoin.py:ro
       - ./plane_autojoin:/code/plane_autojoin:ro
   ```

   `/code` is the backend's working directory (next to `manage.py`), so
   the package is importable there without installing anything. Plane's
   entrypoints only `setdefault` `DJANGO_SETTINGS_MODULE`, so yours wins.

4. **Create the workspace first**, with the slug you configured, before
   anyone else signs up: a user created before the workspace exists does
   not join it later.

5. Turn sign-up on (`ENABLE_SIGNUP`, god-mode → Authentication). With it
   off, Plane only creates accounts for people who already have an invite.

The app has no models and no migrations. Containers only pick up a changed
file when they are recreated, so `docker compose up -d --force-recreate`
after an upgrade.

## Configuration

All variables are read once, at start-up.

| Variable | Meaning |
| --- | --- |
| `PLANE_AUTOJOIN_WORKSPACE_SLUG` | The workspace to join. Several, comma-separated, joins all of them with the same role, and the profile's `last_workspace_id` starts at the first one that exists. Plane's web onboarding then sets it to whichever workspace Plane lists first, so with several workspaces the user may finish onboarding in a different one. **Unset: the app does nothing.** |
| `PLANE_AUTOJOIN_EMAIL_DOMAINS` | Comma-separated email domains, exact match: `example.com` admits `a@example.com`, not `a@sub.example.com`. No wildcards. |
| `PLANE_AUTOJOIN_TRUST_ALL_VERIFIED_EMAILS` | `true` to admit every verified email, whatever the domain. Off by default. Read [Trusting every verified email](#trusting-every-verified-email) first. |
| `PLANE_AUTOJOIN_ROLE` | `member` (or `15`, the default) or `guest` (or `5`). Admin (`20`) is refused. |

With a workspace set, exactly one of `PLANE_AUTOJOIN_EMAIL_DOMAINS` and
`PLANE_AUTOJOIN_TRUST_ALL_VERIFIED_EMAILS=true` must be set. Anything
invalid (both, neither, a wildcard, an unknown role) logs
`auto-join disabled: ...` at start-up and leaves the app off; Plane itself
starts normally.

### Trusting every verified email

Some setups have no meaningful domain to allow: a homelab whose identity
provider brokers consumer accounts on public mail domains and decides who
may reach each app through its own groups. Allowing a public mail domain
there would admit everyone on it. For these,
`PLANE_AUTOJOIN_TRUST_ALL_VERIFIED_EMAILS=true` drops the domain check and
keeps the rest: the email must still be verified, and bots never join.

**Use it only when your identity provider is the only way to create Plane
accounts, and it already enforces who may sign in.** Concretely:

- Turn off password and magic-code login (god-mode → Authentication, or
  `ENABLE_EMAIL_PASSWORD=0` and `ENABLE_MAGIC_LINK_LOGIN=0`). A magic code
  proves only that someone reads a mailbox, not that your IdP let them in.
  In this mode the app checks Plane's instance configuration before each
  join and **skips the join**, logging an error, while either is on (or if
  it cannot read the setting).
- Every OAuth provider you enable must restrict who can sign in. Google:
  an OAuth client with an Internal consent screen (Google Workspace).
  GitHub: set `GITHUB_ORGANIZATION_ID`, or anyone with a GitHub account
  joins. GitLab or Gitea: an instance whose accounts you control.

A warning is logged at start-up whenever this mode is on.

## Which sign-ins count as verified

Read from Plane v1.4.2's `plane/authentication`. Plane sets
`is_email_verified` when it creates a user through an OAuth provider or a
magic code, and never for a password sign-up:

| Sign-in | Verified? | What Plane checks first |
| --- | --- | --- |
| Google | yes | Google's `verified_email` must be `true`. |
| GitHub (github.com only) | yes | Uses the account's primary email, which must be verified; optionally requires membership of `GITHUB_ORGANIZATION_ID`. |
| GitLab (`GITLAB_HOST`, default gitlab.com) | yes | The user must have `confirmed_at`. |
| Gitea (`GITEA_HOST`) | yes | Uses a verified address from `/api/v1/user/emails` (primary first), never an unverified one. |
| Magic code | yes | The code was sent to the address. |
| Email and password | **no** | Nothing; v1.4.2 has no later step that verifies it. |
| God-mode instance admin | **no** | A password sign-up. |

The same providers serve sign-in from published views (`/spaces/`).
Changing a user's email resets the flag, but auto-join only runs when the
account is created.

### Identity providers such as Authentik or Keycloak

Plane CE has no generic OIDC or SAML sign-in: its OAuth providers are
Google, GitHub, GitLab (with a configurable host) and Gitea. The GitLab and
Gitea providers do not speak OIDC discovery: they call fixed paths on the
host (`/oauth/authorize`, `/oauth/token` and `/api/v4/user` for GitLab;
`/login/oauth/authorize`, `/login/oauth/access_token`, `/api/v1/user` and
`/api/v1/user/emails` for Gitea). So a generic IdP needs a GitLab- or
Gitea-compatible bridge in front of it before Plane can use it. This
project does not provide one and has not been tested with one.

If you run such a bridge, the "verified" guarantee is only as good as the
bridge: it must report `confirmed_at` (GitLab shape) or `verified: true`
(Gitea shape) only for addresses the IdP has verified. Plane then marks the
user verified, and `PLANE_AUTOJOIN_TRUST_ALL_VERIFIED_EMAILS` lets the
IdP's own access rules decide who ends up in the workspace.

## Operations

- **Logs**: logger `plane_autojoin` in the `api` container: `auto-join:
  user <id> joined <slug> as role 15` on success; errors name the user id,
  the workspace and the exception class.
- **A new user landed on "create a workspace"**: auto-join did not run.
  Look for `auto-join` lines (workspace not found, `auto-join disabled`,
  sign-in settings in trust-all mode), check the variables with
  `docker compose exec api env | grep PLANE_AUTOJOIN`, then invite the
  person by hand.
- **Promote someone**: workspace settings → Members. The app never changes
  an existing membership's role.
- **Turn it off**: unset `PLANE_AUTOJOIN_WORKSPACE_SLUG` and recreate the
  containers. If nothing else lets new users in, also turn sign-up off.

## Compatibility

| plane-autojoin | Plane CE (backend image) | Python | Django |
| --- | --- | --- | --- |
| 0.1.x | v1.4.2 | 3.12 | 5.2 |

It reads and writes Plane's `User`, `Profile`, `Workspace` and
`WorkspaceMember` models and calls `plane.utils.cache.invalidate_cache_directly`
and `plane.license.utils.instance_value.get_configuration_value`. Before an
upgrade, bump the image in `integration/compose.yml`, run the integration
test, and re-read the files named at the top of
`src/plane_autojoin/receivers.py`.

## Upstream

We have proposed domain auto-join to Plane upstream, as a setting in the
sign-up path itself. If Plane ships it, prefer the built-in feature and
drop this app.

## Development

```sh
uv sync
uv run pytest                     # unit tests: SQLite and stand-in Plane models
uv run ruff check . && uv run ruff format --check .
./integration/run.sh              # Docker: Plane's real backend image + Postgres + Valkey
```

The unit tests replace Plane with a few stand-in models and helpers
(`tests/fakeplane/`), so they need no Plane checkout. The integration test
mounts the package into the pinned `makeplane/plane-backend` image the way
the install steps above do, migrates a throwaway Postgres, and signs users
up through Plane's own `Adapter.complete_login_or_signup()`: an allowed
domain joins, another domain and an unverified (password) sign-up do not,
repeating the sign-in and the join is idempotent, the profile fields are
set, and trust-all mode joins any verified domain but refuses while
magic-code login is on. CI runs both on every pull request; it takes
about a minute plus the image pull.

## Releasing

Bump `version` in `pyproject.toml`, add a `CHANGELOG.md` section, merge,
then push a tag `vX.Y.Z`. The release workflow runs CI, builds the sdist
and wheel with `uv build`, and publishes them with a `SHA256SUMS` file as a
GitHub Release. Nothing is published to PyPI; that may come later.

## Licence

[MIT](LICENSE). plane-autojoin is not affiliated with Plane and contains no
Plane code. Plane is licensed under the AGPL-3.0.

"""Request identity and tenant-boundary helpers for the HTTP APIs.

The research API historically accepted ``X-Role`` and ``X-Tenant-ID`` as
development/integration headers.  Those values are convenient for local
clients, but are not an enterprise identity boundary because a browser can
forge them.  This module adds a deliberately small, opt-in trusted identity
adapter:

* ``EQUIPMENT_DR_REQUIRE_TRUSTED_IDENTITY=1`` (or
  ``EQUIPMENT_DR_AUTH_MODE=trusted_headers``) requires a tenant claim from a
  gateway-injected ``X-Authenticated-*`` header.
* In compatibility mode, existing ``X-*`` scope headers continue to work.
* When trusted claims are present, the middleware rejects conflicting legacy
  headers and projects the trusted claims onto the headers consumed by the
  existing route handlers.

The trusted headers must only be accepted from a reverse proxy that strips
client-supplied copies.  This is an adapter, not a replacement for OIDC/JWT
verification at the edge; deployments may put a verified OIDC gateway in
front of it without changing application routes.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from collections.abc import Mapping, MutableMapping
from typing import Any, Callable

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


_TRUTHY = {"1", "true", "yes", "on", "all"}
_FALSEY = {"0", "false", "no", "off", "none", ""}
_KNOWN_ROLES = {"analyst", "developer", "reviewer", "auditor", "admin"}


def _text(value: object, limit: int = 160) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _header(headers: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = headers.get(name.lower(), "")
        if value and value.strip():
            return _text(value)
    return ""


def _roles(value: object) -> tuple[str, ...]:
    raw = str(value or "")
    result: list[str] = []
    for item in raw.replace(";", ",").replace(" ", ",").split(","):
        role = item.strip().lower()
        if role in _KNOWN_ROLES and role not in result:
            result.append(role)
    return tuple(result)


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def strict_auth_enabled(explicit: bool | None = None) -> bool:
    """Return whether trusted identity is required for protected routes.

    ``explicit`` is useful for tests and embedding applications.  Environment
    aliases intentionally cover the names used by deployment manifests over
    time while keeping the default backwards compatible.
    """

    if explicit is not None:
        return bool(explicit)
    raw = os.environ.get("EQUIPMENT_DR_REQUIRE_TRUSTED_IDENTITY")
    if raw is None:
        raw = os.environ.get("EQUIPMENT_DR_STRICT_AUTH")
    if raw is None:
        mode = os.environ.get("EQUIPMENT_DR_AUTH_MODE", "legacy")
        return str(mode).strip().lower() in {
            "trusted",
            "trusted_headers",
            "strict",
            "oidc",
            "jwt",
        }
    if str(raw).strip().lower() in _FALSEY:
        return False
    return str(raw).strip().lower() in _TRUTHY


@dataclass(frozen=True)
class TenantContext:
    """Normalized request identity and namespace claims."""

    tenant_id: str = ""
    workspace_id: str = ""
    project_id: str = ""
    profile_id: str = ""
    user_id: str = ""
    roles: tuple[str, ...] = ()
    authenticated: bool = False
    source: str = "none"

    @property
    def role(self) -> str:
        # Preserve the application's existing single-role contract.  A
        # stronger role wins when a gateway supplies multiple claims.
        for role in ("admin", "auditor", "reviewer", "developer", "analyst"):
            if role in self.roles:
                return role
        return "analyst"

    @property
    def supplied(self) -> bool:
        return bool(
            self.tenant_id
            or self.workspace_id
            or self.project_id
            or self.profile_id
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "profile_id": self.profile_id,
            "user_id": self.user_id,
            "roles": list(self.roles),
            "role": self.role,
            "authenticated": self.authenticated,
            "source": self.source,
        }


def resolve_tenant_context(
    headers: Mapping[str, str], *, strict: bool | None = None
) -> tuple[TenantContext, bool]:
    """Resolve trusted or compatibility headers.

    Returns ``(context, conflict)``.  A conflict means a trusted claim and a
    legacy browser-provided scope/role disagree; callers should fail closed.
    In compatibility mode legacy headers are still accepted exactly as before.
    """

    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    trusted_tenant = _header(
        normalized,
        "x-authenticated-tenant-id",
        "x-auth-tenant-id",
        "x-principal-tenant-id",
    )
    trusted_workspace = _header(
        normalized,
        "x-authenticated-workspace-id",
        "x-auth-workspace-id",
        "x-principal-workspace-id",
    )
    trusted_project = _header(
        normalized,
        "x-authenticated-project-id",
        "x-auth-project-id",
        "x-principal-project-id",
    )
    trusted_profile = _header(
        normalized,
        "x-authenticated-profile-id",
        "x-auth-profile-id",
        "x-principal-profile-id",
    )
    trusted_user = _header(
        normalized,
        "x-authenticated-user-id",
        "x-auth-user-id",
        "x-principal-user-id",
    )
    trusted_roles = _roles(
        _header(
            normalized,
            "x-authenticated-roles",
            "x-auth-roles",
            "x-principal-roles",
        )
    )
    trusted_supplied = bool(
        trusted_tenant
        or trusted_workspace
        or trusted_project
        or trusted_profile
        or trusted_user
        or trusted_roles
    )
    legacy_tenant = _header(normalized, "x-tenant-id")
    legacy_workspace = _header(normalized, "x-workspace-id")
    legacy_project = _header(normalized, "x-project-id")
    legacy_profile = _header(normalized, "x-profile-id")
    legacy_user = _header(normalized, "x-user-id")
    legacy_roles = _roles(_header(normalized, "x-role"))
    conflict = False
    if trusted_supplied:
        for trusted, legacy in (
            (trusted_tenant, legacy_tenant),
            (trusted_workspace, legacy_workspace),
            (trusted_project, legacy_project),
            (trusted_profile, legacy_profile),
            (trusted_user, legacy_user),
        ):
            if trusted and legacy and trusted != legacy:
                conflict = True
        if trusted_roles and legacy_roles and not set(trusted_roles).intersection(legacy_roles):
            conflict = True
        context = TenantContext(
            tenant_id=trusted_tenant,
            workspace_id=trusted_workspace,
            project_id=trusted_project,
            profile_id=trusted_profile,
            user_id=trusted_user,
            # Never derive authorization from the caller-controlled legacy
            # X-Role when a trusted identity claim is present.  A gateway
            # that omits roles intentionally gets the least-privileged
            # default (analyst).
            roles=trusted_roles,
            authenticated=bool(trusted_tenant),
            source="trusted_headers",
        )
    else:
        context = TenantContext(
            tenant_id=legacy_tenant,
            workspace_id=legacy_workspace,
            project_id=legacy_project,
            profile_id=legacy_profile,
            user_id=legacy_user,
            roles=legacy_roles,
            authenticated=False,
            source="legacy_headers" if (legacy_tenant or legacy_user or legacy_roles) else "none",
        )
    if strict is None:
        strict = strict_auth_enabled()
    # A strict deployment cannot treat a plain X-Tenant-ID as authentication.
    if strict and not context.authenticated:
        return context, conflict
    return context, conflict


def cross_scope_requested(headers: Mapping[str, str]) -> bool:
    normalized = {str(k).lower(): str(v) for k, v in headers.items()}
    return _truthy(
        _header(
            normalized,
            "x-tenant-cross-scope",
            "x-evolution-cross-scope",
        )
    )


def scope_matches(
    resource: Mapping[str, Any] | object,
    context: TenantContext,
    *,
    allow_global: bool = False,
    cross_scope: bool = False,
) -> bool:
    """Check a resource namespace against the request context.

    Empty resource scope is legacy/global data.  It is intentionally not
    visible to a tenant-scoped request unless ``allow_global`` is explicitly
    requested by a trusted platform administrator.
    """

    if cross_scope and "admin" in context.roles:
        return True
    if not context.supplied:
        return True
    values = resource if isinstance(resource, Mapping) else getattr(resource, "__dict__", {})
    values = values if isinstance(values, Mapping) else {}
    nested = values.get("scope") if isinstance(values.get("scope"), Mapping) else {}
    for key in ("tenant_id", "workspace_id", "project_id", "profile_id"):
        actual = _text(values.get(key) or nested.get(key, ""))
        expected = _text(getattr(context, key, ""))
        if expected:
            if actual != expected:
                return False
        elif actual:
            return False
    if not any(_text(values.get(key) or nested.get(key, "")) for key in ("tenant_id", "workspace_id", "project_id", "profile_id")):
        return bool(allow_global)
    return True


def _is_public_path(path: str) -> bool:
    return path in {
        "/api/v1/health",
        "/api/v1/query-library/health",
        "/openapi.json",
        "/docs",
        "/redoc",
    } or path.startswith("/docs/") or path.startswith("/redoc/")


def _replace_scope_headers(scope: MutableMapping[str, Any], context: TenantContext) -> None:
    """Project verified claims onto legacy headers consumed by route code."""

    replacements = {
        "x-tenant-id": context.tenant_id,
        "x-workspace-id": context.workspace_id,
        "x-project-id": context.project_id,
        "x-profile-id": context.profile_id,
        "x-user-id": context.user_id,
        "x-role": context.role,
    }
    raw_headers = list(scope.get("headers") or [])
    result: list[tuple[bytes, bytes]] = []
    seen: set[str] = set()
    for name, value in raw_headers:
        key = name.decode("latin-1").lower()
        if key in replacements:
            if key in seen:
                continue
            seen.add(key)
            result.append((name, replacements[key].encode("latin-1")))
        else:
            result.append((name, value))
    for key, value in replacements.items():
        if value and key not in seen:
            result.append((key.encode("latin-1"), value.encode("latin-1")))
    scope["headers"] = result


def install_tenant_auth_middleware(
    app: ASGIApp,
    *,
    strict: bool | None = None,
    run_loader: Callable[[str], object | None] | None = None,
) -> ASGIApp:
    """Install trusted identity + run namespace protection on an ASGI app.

    The function returns the app for convenient embedding.  A Starlette
    middleware class is used instead of a route dependency so every existing
    run sub-route (including SSE and artifact downloads) receives the same
    pre-handler check.
    """

    enabled = strict_auth_enabled(strict)

    class _TenantAuthMiddleware:
        def __init__(self, inner: ASGIApp) -> None:
            self.inner = inner

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope.get("type") != "http":
                await self.inner(scope, receive, send)
                return
            path = str(scope.get("path", ""))
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope.get("headers", [])
            }
            context, conflict = resolve_tenant_context(headers, strict=enabled)
            # ``state`` is copied by Starlette's Request wrapper.  Preserve an
            # existing mapping when another middleware initialized it.
            state = scope.setdefault("state", {})
            if isinstance(state, MutableMapping):
                state["tenant_context"] = context
                state["tenant_auth_conflict"] = conflict
            if conflict:
                await JSONResponse(
                    {"detail": "trusted identity conflicts with request scope"},
                    status_code=403,
                )(scope, receive, send)
                return
            if enabled and not _is_public_path(path) and not context.authenticated:
                await JSONResponse(
                    {"detail": "authenticated tenant context is required"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )(scope, receive, send)
                return
            if context.authenticated:
                # Existing route handlers intentionally remain unchanged and
                # read X-* values.  Only verified gateway claims are projected.
                _replace_scope_headers(scope, context)
            # A caller that supplies a namespace is asking for a scoped view,
            # even in compatibility mode.  This closes the common accidental
            # cross-tenant read/write path while requests with no scope retain
            # the legacy global behavior.
            if run_loader is not None and context.supplied and path.startswith("/api/v1/runs/"):
                parts = [item for item in path.split("/") if item]
                # ``runs/permanent-delete`` is a batch route; it is checked in
                # the handler because the body contains multiple IDs.
                if len(parts) >= 4 and parts[2] == "runs":
                    run_id = parts[3]
                    if run_id not in {"permanent-delete"} and context.supplied:
                        try:
                            resource = run_loader(run_id)
                        except Exception as exc:
                            # A missing run is allowed to reach the route so
                            # its normal 404 contract is preserved.  Any
                            # other loader failure (database outage, decode
                            # error, permission backend failure) must fail
                            # closed; treating it as ``None`` would let a
                            # scoped caller probe or access a resource while
                            # the namespace check is unavailable.
                            if getattr(exc, "status_code", None) in {400, 404} or exc.__class__.__name__ in {
                                "RunNotFoundError",
                                "NoResultFound",
                                "KeyError",
                            }:
                                resource = None
                            else:
                                await JSONResponse(
                                    {"detail": "tenant scope could not be verified"},
                                    status_code=503,
                                )(scope, receive, send)
                                return
                        if resource is not None and not scope_matches(
                            resource,
                            context,
                            # Cross-scope is a privileged gateway operation,
                            # never a capability of a caller-controlled
                            # ``X-Role: admin`` compatibility header.  The
                            # trusted identity adapter must have authenticated
                            # the tenant and asserted the admin role before
                            # this bypass is honored.
                            cross_scope=(
                                context.authenticated
                                and "admin" in context.roles
                                and cross_scope_requested(headers)
                            ),
                        ):
                            await JSONResponse(
                                {"detail": "tenant scope mismatch"}, status_code=403
                            )(scope, receive, send)
                            return
            await self.inner(scope, receive, send)

    # FastAPI exposes ``add_middleware`` but keeping this helper ASGI-generic
    # makes it usable by the standalone query-library app as well.
    if hasattr(app, "add_middleware"):
        app.add_middleware(_TenantAuthMiddleware)
    else:
        raise TypeError("app must expose add_middleware")
    return app


__all__ = [
    "TenantContext",
    "cross_scope_requested",
    "install_tenant_auth_middleware",
    "resolve_tenant_context",
    "scope_matches",
    "strict_auth_enabled",
]

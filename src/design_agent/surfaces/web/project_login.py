"""Browser-bound root sign-in handoffs. Refresh credentials stay on the sign-in host."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import time
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlencode, urlsplit

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from design_agent.surfaces.web.directory import Directory

if TYPE_CHECKING:
    from design_agent.surfaces.web.auth import Auth, Tenants

PROJECT_SESSION = "incredible-project"
BROWSER_SESSION = "incredible-browser"
RETURN_COOKIE = "incredible-project-proof"
FINISH = "/api/auth/finish"
FLOW_ID = re.compile(r"[0-9a-f]{32}")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def local_path(value: str) -> str:
    decoded = unquote(value)
    if (
        len(value) > 4096
        or not value.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or any(ord(c) < 32 for c in decoded)
        or any(part in {".", ".."} for part in decoded.split("?")[0].split("/"))
    ):
        raise HTTPException(400, "Invalid project page.")
    if urlsplit(decoded).path.split("/")[1] not in {
        "",
        "invite",
        "settings",
        "c",
        "needs-you",
        "skills",
        "computer",
        "production",
        "brand",
    }:
        raise HTTPException(400, "Invalid project page.")
    return value


def begin_url(origin: str, path: str) -> str:
    return origin + "/api/auth/start?" + urlencode({"next": path})


class Landing(BaseModel):
    path: str = "/"
    flow: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    organization: str | None = Field(default=None, min_length=1, max_length=100)


def project_login_routes(auth: Auth, directory: Directory, tenants: Tenants) -> APIRouter:
    router = APIRouter()

    async def authorize(user: dict[str, Any], project: str, path: str) -> dict[str, Any]:
        invite = re.fullmatch(r"/invite/([0-9a-f]{32})/?", urlsplit(path).path)
        if not invite:
            return await directory.project(user, project)
        rows = await directory.query(
            "SELECT a.id,a.email FROM invitations i JOIN accounts a ON a.id=i.owner "
            "WHERE i.id=? AND i.owner=? AND (i.member=? OR (i.member IS NULL AND i.email=?))",
            invite[1],
            project,
            user["id"],
            user["email"].lower(),
        )
        if not rows:
            raise HTTPException(
                403,
                "This invitation is unavailable for this account. Sign in with the invited email or ask the owner for a new link.",
            )

        return rows[0]

    @router.get("/api/auth/start")
    async def start(request: Request, next: str = "/") -> RedirectResponse:
        project = await auth.project_host(request)
        if not project:
            raise HTTPException(400, "Open a project address to continue.")
        path = local_path(next)
        auth.throttle(request, scope="project-entry", limit=120)
        flow, proof = uuid.uuid4().hex, secrets.token_urlsafe(32)
        now = time.time()
        await directory.query("DELETE FROM project_handoffs WHERE expires<=?", now)
        await directory.query(
            "INSERT INTO project_handoffs(flow,proof,project,path,expires) VALUES(?,?,?,?,?)",
            flow,
            digest(proof),
            auth.host_label(request),
            path,
            now + 86400,
        )
        response = RedirectResponse(auth.origin + "/?flow=" + flow, status_code=303)
        # Independent cookies allow two tabs to complete different invitations.
        response.set_cookie(
            RETURN_COOKIE + "-" + flow,
            proof,
            path=FINISH,
            httponly=True,
            secure=auth.secure,
            samesite="lax",
            max_age=86400,
        )
        return response

    @router.post("/api/auth/land")
    async def land(request: Request, body: Landing) -> JSONResponse:
        await auth.origin_check(request)
        if await auth.project_host(request):
            raise HTTPException(400, "Continue from the Studio sign-in address.")
        user, fresh = await auth.identity(request)
        actor = user["id"]

        def reply(data: dict[str, Any]) -> JSONResponse:
            response = JSONResponse(data)
            if fresh:
                auth.cookies(response, fresh)
            return response

        if not body.flow:
            path = local_path(body.path)
            visits = await directory.query(
                "SELECT project FROM project_visits WHERE actor=?", actor
            )
            if not visits:
                # Accounts from before canonical project hosts already have navigation history.
                visits = await directory.query(
                    "SELECT owner AS project FROM activity WHERE actor=? AND action LIKE ? "
                    "AND status=200 ORDER BY happened DESC LIMIT 1",
                    actor,
                    "View %",
                )
            project = actor
            if visits and path == "/" and visits[0]["project"] != actor:
                shared = await directory.query(
                    "SELECT owner FROM invitations WHERE member=? AND owner=?",
                    actor,
                    visits[0]["project"],
                )
                if shared:
                    project = shared[0]["owner"]
            saved_name = None
            if not visits and path == "/":
                tenant = await tenants.get(user)
                host = getattr(tenant.state, "host", None)
                organization = await asyncio.to_thread(host.store.organization) if host else {}
                if not organization.get("name"):
                    if not body.organization:
                        return reply({"needs_organization": True})
                    name = body.organization.strip()
                    if not name:
                        raise HTTPException(422, "Enter an organization name.")
                    if host:
                        await asyncio.to_thread(host.store.name_new_organization, name)
                    else:
                        saved_name = name
            owner = await directory.project(user, project)
            return reply(
                {"url": begin_url(await tenants.project_url(auth, owner, saved_name), path)}
            )

        rows = await directory.query(
            "SELECT project,path FROM project_handoffs WHERE flow=? AND expires>?",
            body.flow,
            time.time(),
        )
        if not rows:
            raise HTTPException(410, "This sign-in link expired. Reopen the original project link.")
        label, path = rows[0]["project"], rows[0]["path"]
        project = await directory.project_for_label(label)
        if not project:
            raise HTTPException(404, "Project address not found.")
        owner = await authorize(user, project, path)
        origin = await tenants.project_url(auth, owner)
        if auth.host_url(label) != origin:
            # Browser proofs are host-only. Start a fresh handoff on the canonical host.
            return reply({"url": begin_url(origin, path)})
        key = Fernet.generate_key()
        code = key.decode()
        response = reply(
            {"url": origin + FINISH + "?" + urlencode({"flow": body.flow, "code": code})}
        )
        session = request.cookies.get(BROWSER_SESSION) or await auth.new_browser(response, actor)
        access = fresh["access_token"] if fresh else request.cookies["incredible-access"]
        payload = Fernet(key).encrypt(json.dumps([actor, access]).encode()).decode()
        updated = await directory.query(
            "UPDATE project_handoffs SET code=?,payload=?,session=?,expires=? "
            "WHERE flow=? AND expires>? RETURNING flow",
            digest(code),
            payload,
            digest(session),
            time.time() + 60,
            body.flow,
            time.time(),
        )
        if not updated:
            raise HTTPException(410, "Reopen the project link to continue.")
        return response

    @router.get(FINISH)
    async def finish(request: Request, flow: str, code: str) -> RedirectResponse:
        project = await auth.project_host(request)
        proof = request.cookies.get(RETURN_COOKIE + "-" + flow)
        denied = HTTPException(
            403, "Sign-in link expired or unavailable. Reopen the project address."
        )
        if not project or not proof or not FLOW_ID.fullmatch(flow) or len(code) != 44:
            raise denied
        rows = await directory.query(
            "DELETE FROM project_handoffs WHERE flow=? AND project=? AND proof=? AND code=? "
            "AND expires>? RETURNING path,payload,session",
            flow,
            auth.host_label(request),
            digest(proof),
            digest(code),
            time.time(),
        )
        if not rows:
            raise denied
        row = rows[0]
        actor, access = json.loads(Fernet(code.encode()).decrypt(row["payload"].encode()))
        active = await directory.query(
            "SELECT actor FROM browser_sessions WHERE id=? AND actor=? AND expires>?",
            row["session"],
            actor,
            time.time(),
        )
        user = await auth.user(access) if active else None
        if not user or user["id"] != actor:
            raise denied
        await authorize(user, project, row["path"])
        response = RedirectResponse(row["path"], status_code=303)
        await auth.project_cookie(response, project, row["session"], access)
        for cookie in ("incredible-access", "incredible-refresh", BROWSER_SESSION):
            response.delete_cookie(cookie, secure=auth.secure, httponly=True, samesite="lax")
        response.delete_cookie(
            RETURN_COOKIE + "-" + flow,
            path=FINISH,
            secure=auth.secure,
            httponly=True,
            samesite="lax",
        )
        return response

    return router

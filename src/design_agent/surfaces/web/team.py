"""Project membership, account settings and activity routes."""

import asyncio
import sqlite3
import uuid
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from design_agent.surfaces.web.auth import Auth, Tenants

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, EmailStr, Field

from design_agent.surfaces.web.directory import Directory
from design_agent.surfaces.web.invite_mail import send_invitation


class Interaction(BaseModel):
    action: Literal[
        "View channel",
        "View needs",
        "View production",
        "View brand",
        "View read-brand",
        "View skills",
        "View computer",
        "View settings",
        "View preferences",
        "View profile",
        "View organization",
        "View members",
        "View logs",
        "View usage",
        "View episode",
        "View canvas",
        "Change start page",
        "Change time format",
        "Change theme",
    ]


class Invitation(BaseModel):
    email: EmailStr


class AccountDetails(BaseModel):
    username: str = Field(default="", pattern=r"^([a-zA-Z0-9_]{3,32})?$")
    first_name: str = Field(default="", max_length=80)
    last_name: str = Field(default="", max_length=80)


def team_routes(auth: "Auth", directory: Directory, tenants: "Tenants") -> APIRouter:
    router = APIRouter()

    async def context(
        request: Request, personal: bool = False
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
        if request.method != "GET":
            await auth.origin_check(request)
        actor, tokens = await auth.identity(request)
        project = await directory.project(
            actor, None if personal else await auth.project_host(request)
        )
        request.state.project = project["id"]
        return actor, project, tokens

    def reply(data: Any, tokens: Any) -> JSONResponse:
        response = JSONResponse(data)
        if tokens:
            auth.cookies(response, tokens)
        return response

    async def invite_url(owner: dict[str, Any], invite_id: str) -> str:
        return f"{await tenants.project_url(auth, owner)}/invite/{invite_id}"

    async def project_name(owner: dict[str, Any]) -> str:
        app = await tenants.get(owner)
        host = getattr(app.state, "host", None)
        profile = await asyncio.to_thread(host.store.organization) if host else {}
        return profile.get("name") or f"{owner['email']}’s project"

    @router.get("/api/account/details")
    async def details(request: Request) -> JSONResponse:
        actor, _, tokens = await context(request, True)
        rows = await directory.query(
            "SELECT username, first_name,last_name FROM accounts WHERE id=?", actor["id"]
        )
        return reply(rows[0] if rows else {}, tokens)

    @router.put("/api/account/details")
    async def save_details(request: Request, body: AccountDetails) -> JSONResponse:
        actor, _, tokens = await context(request, True)
        try:
            await directory.query(
                "INSERT INTO accounts(id,email,username,first_name,last_name) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET email=excluded.email,username=excluded.username,"
                "first_name=excluded.first_name,last_name=excluded.last_name",
                actor["id"],
                actor["email"],
                body.username.lower() or None,
                body.first_name.strip(),
                body.last_name.strip(),
            )
        except (UniqueViolation, sqlite3.IntegrityError):
            raise HTTPException(409, "That username is already in use.") from None
        return reply(
            {
                "username": body.username.lower() or None,
                "first_name": body.first_name.strip(),
                "last_name": body.last_name.strip(),
            },
            tokens,
        )

    @router.get("/api/team")
    async def team(request: Request) -> JSONResponse:
        actor, project, tokens = await context(request)
        members = await directory.query(
            "SELECT id,email,member FROM invitations WHERE owner=? ORDER BY email", project["id"]
        )
        if project["id"] == actor["id"] and members:
            origin = await tenants.project_url(auth, project)
            for row in members:
                if not row["member"]:
                    row["invite_url"] = origin + "/invite/" + row["id"]
        incoming = await directory.query(
            "SELECT i.id,i.owner,a.email,i.member FROM invitations i JOIN accounts a ON a.id=i.owner "
            "WHERE i.member=? OR (i.email=? AND i.member IS NULL) ORDER BY a.email",
            actor["id"],
            actor["email"].lower(),
        )
        for row in incoming:
            origin = await tenants.project_url(auth, {"id": row["owner"], "email": row["email"]})
            row["url"] = origin + (
                "/settings/organization" if row["member"] else "/invite/" + row["id"]
            )
        return reply(
            {
                "project": project["id"],
                "personal_url": await tenants.project_url(auth, actor),
                "owner": project["email"],
                "can_manage": project["id"] == actor["id"],
                "members": members,
                "incoming": incoming,
            },
            tokens,
        )

    @router.post("/api/team/invite")
    async def invite(request: Request, body: Invitation) -> JSONResponse:
        actor, project, tokens = await context(request)
        if actor["id"] != project["id"]:
            raise HTTPException(403, "Only the owner can invite members.")
        email = str(body.email).lower()
        if email == actor["email"].lower():
            raise HTTPException(409, "You already own this project.")
        await directory.query(
            "INSERT INTO accounts(id,email) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET email=excluded.email",
            actor["id"],
            actor["email"],
        )
        auth.throttle(request)
        organization = await project_name(project)
        invite_id = uuid.uuid4().hex
        rows = await directory.query(
            "INSERT INTO invitations(id,owner,email) VALUES(?,?,?) ON CONFLICT DO NOTHING RETURNING id",
            invite_id,
            actor["id"],
            email,
        )
        if not rows:
            raise HTTPException(409, "This person already has an invitation or access.")
        request.state.member_email = email
        link = await invite_url(project, invite_id)
        sent = await asyncio.to_thread(
            send_invitation, tenants.settings, email, organization, actor["email"], link
        )
        return reply({"id": invite_id, "invite_url": link, "email_sent": sent}, tokens)

    @router.get("/api/team/{invite_id}")
    async def preview(request: Request, invite_id: str) -> JSONResponse:
        actor, _, tokens = await context(request, True)
        rows = await directory.query(
            "SELECT a.id,a.email,i.member FROM invitations i JOIN accounts a ON a.id=i.owner "
            "WHERE i.id=? AND i.owner=? AND (i.member=? OR (i.member IS NULL AND i.email=?))",
            invite_id,
            await auth.project_host(request),
            actor["id"],
            actor["email"].lower(),
        )
        if not rows:
            raise HTTPException(
                403,
                "This invitation is unavailable for this account. Sign in with the invited email, or ask the owner for a new link.",
            )
        return reply(
            {"organization": await project_name(rows[0]), "accepted": bool(rows[0]["member"])},
            tokens,
        )

    @router.post("/api/team/{invite_id}/accept")
    async def accept(request: Request, invite_id: str) -> JSONResponse:
        actor, _, tokens = await context(request, True)
        project_host = await auth.project_host(request)
        rows = await directory.query(
            "UPDATE invitations SET member=? WHERE id=? AND (owner=? OR ?='') AND "
            "(member=? OR (member IS NULL AND email=?)) RETURNING owner",
            actor["id"],
            invite_id,
            project_host or "",
            project_host or "",
            actor["id"],
            actor["email"].lower(),
        )
        if not rows:
            raise HTTPException(403, "This invitation is unavailable for your account.")
        request.state.project = rows[0]["owner"]
        request.state.member_email = actor["email"]
        owner = await directory.project(actor, rows[0]["owner"])
        return reply({"url": await tenants.project_url(auth, owner)}, tokens)

    @router.delete("/api/team/{invite_id}")
    async def remove(request: Request, invite_id: str) -> JSONResponse:
        actor, project, tokens = await context(request)
        if actor["id"] != project["id"]:
            raise HTTPException(403, "Only the owner can revoke access.")
        rows = await directory.query(
            "DELETE FROM invitations WHERE owner=? AND id=? RETURNING member,email",
            actor["id"],
            invite_id,
        )
        if not rows:
            raise HTTPException(404, "Invitation or member not found.")
        request.state.member_email = rows[0]["email"]
        if rows[0]["member"] and hasattr(
            getattr(tenants.apps.get(project["id"]), "state", None), "host"
        ):
            tenants.apps[project["id"]].state.host.hub.close_streams()
        return reply({"ok": True}, tokens)

    @router.post("/api/activity/interaction")
    async def interaction(request: Request, body: Interaction) -> JSONResponse:
        _, _, tokens = await context(request)
        request.state.client_action = body.action
        return reply({"ok": True}, tokens)

    @router.get("/api/activity")
    async def activity(request: Request, actor_id: str = "", before: float = 1e12) -> JSONResponse:
        _, project, tokens = await context(request)
        rows = await directory.query(
            "SELECT id,actor,actor_email,action,happened,status,member_email,duration_ms FROM activity WHERE owner=? AND happened<? "
            "AND (?='' OR actor=?) ORDER BY happened DESC LIMIT 51",
            project["id"],
            before,
            actor_id,
            actor_id,
        )
        actors = await directory.query(
            "SELECT actor,MAX(actor_email) AS email FROM activity WHERE owner=? GROUP BY actor ORDER BY email",
            project["id"],
        )
        return reply(
            {"events": rows[:50], "actors": actors, "more": len(rows) > 50},
            tokens,
        )

    return router

"""The launch film's production as a pipeline: plan, lead act, acts, assembly, final review, the
person's approval, final render.

The lead ran production from `skills/launch-film/` one model turn per step, so a review could be
skipped, or assembly could start before an act was checked. Here the order and the gates are code,
and every judgment stays with the helpers: each step's brief points at the skill's own brief
(`/skills/launch-film/briefs/<file>`) by its sandbox path and passes the values to fill in.

It starts where the person's approvals end (SKILL.md sections 1-4): BRIEF.md, the approved
storyboard and animatic, and a frozen timeline.js in `/workspace/projects/<project>/`. Then:
1. Plan (max): the acts, the shared rig, and one filled act-builder brief per act.
2. Lead act (max): the system-defining act, with the shared rig proven and frozen, and API.md.
3. Acts, with no barrier between stages: each act is built (xhigh or max, as the plan says),
   reviewed by a critic the moment it lands (xhigh), and given one fix pass (xhigh) when the review
   doesn't pass. The lead act is reviewed the same way while the others build. At most
   `builders_at_once` builders share the sandbox (orchestration.md: three on 8 vCPU).
4. Assembly (xhigh), then the final review (max).
5. The person approves the final render, or asks for changes: a revision pass (xhigh), then
   assembly and the final review again, and the question again.
6. Final render (low). Delivery stays with the lead: helpers never deliver.

A step whose helper fails is re-issued once under the resume preamble (SKILL.md section 6). An act
that still fails stops the run once the other acts are done, and the lead decides: resume the run
(finished steps replay) or split the act.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from typing import Any

from design_agent.harness.workflow import Step, StepFailed, WorkflowContext

SKILL = "/skills/launch-film/SKILL.md"
ORCHESTRATION = "/skills/launch-film/orchestration.md"
BRIEFS = "/skills/launch-film/briefs"
#: Builders one 8-vCPU sandbox holds at once (orchestration.md, "Waves"): an argument, for a bigger box.
BUILDERS_AT_ONCE = 3
#: The answers to "Render the final?". Anything that doesn't start with "approve" asks for changes.
APPROVE, CHANGES = "approve", "changes"

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["acts", "rig"],
    "properties": {
        "acts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["name", "seconds", "effort", "brief"],
                "properties": {
                    "name": {"type": "string"},
                    "seconds": {"type": "number"},
                    "effort": {"enum": ["xhigh", "max"]},
                    "brief": {"type": "string"},
                },
            },
        },
        "rig": {"type": "string"},
    },
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["score", "pass", "issues"],
    "properties": {
        "score": {"type": "number"},
        "pass": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
}

_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


async def launch_film(
    ctx: WorkflowContext,
    *,
    project: str,
    notes: str = "",
    builders_at_once: int = BUILDERS_AT_ONCE,
) -> dict[str, Any]:
    """A launch film's production, from its approved animatic to the final master: plan, lead act,
    every other act with a review as it lands, assembly, final review, the person's approval, and
    the final render. `project` is its folder under /workspace/projects/; `notes` go to the planner."""
    if not _PROJECT.fullmatch(project):
        raise ValueError(f"project is a folder name under /workspace/projects/, not {project!r}")
    work = f"/workspace/projects/{project}"

    ctx.phase("plan")
    plan = await _step(ctx, _plan(work, notes), effort="max", label="plan", schema=PLAN_SCHEMA)
    lead, *others = plan.value["acts"]
    count = len(plan.value["acts"])

    ctx.phase("lead act")
    lead_build = await _step(
        ctx, _lead(work, lead, str(plan.value["rig"])), effort="max", label=_label(lead, "build")
    )

    ctx.phase("acts")
    builders = asyncio.Semaphore(max(1, builders_at_once))

    async def build(item: dict[str, Any]) -> dict[str, Any]:
        if item["build"] is not None:
            return item
        act = item["act"]
        async with builders:
            step = await _step(
                ctx,
                _build(work, act, count, lead, lead_build),
                effort=item["effort"],
                label=_label(act, "build"),
            )
        return {**item, "build": step}

    async def review(item: dict[str, Any]) -> dict[str, Any]:
        act = item["act"]
        step = await _step(
            ctx,
            _review(work, act, item["build"]),
            effort="xhigh",
            label=_label(act, "review"),
            schema=REVIEW_SCHEMA,
        )
        return {**item, "review": step.value}

    async def fix(item: dict[str, Any]) -> dict[str, Any]:
        if item["review"]["pass"]:
            return {**item, "fix": None}
        act = item["act"]
        async with builders:
            step = await _step(
                ctx, _fix(work, act, item["review"]), effort="xhigh", label=_label(act, "fix")
            )
        return {**item, "fix": step}

    items = [
        {"act": lead, "effort": "max", "build": lead_build},
        *({"act": act, "effort": act["effort"], "build": None} for act in others),
    ]
    acts = await ctx.pipeline(items, build, review, fix)
    unfinished = [item["act"]["name"] for item, done in zip(items, acts, strict=True) if not done]
    if unfinished:
        raise RuntimeError(
            f"{', '.join(unfinished)} didn't finish: a step failed twice (see its step notes). "
            "Every other act is saved; resume this run to try again, or split the act at its next "
            "hard cut (SKILL.md section 6)."
        )
    ctx.note(
        "Every act is built and reviewed: "
        + "; ".join(
            f"{a['act']['name']} {a['review']['score']}/5{', fixed' if a['fix'] else ''}"
            for a in acts
        )
        + "."
    )

    round_, revision = 1, ""
    while True:
        ctx.phase("assembly")
        assembly = await _step(
            ctx, _assembly(work, acts, round_, revision), effort="xhigh", label=f"assembly {round_}"
        )
        ctx.phase("final review")
        verdict = (
            await _step(
                ctx,
                _final_review(work, assembly, round_),
                effort="max",
                label=f"final review {round_}",
                schema=REVIEW_SCHEMA,
            )
        ).value
        ctx.phase("approval")
        answer = await ctx.ask(_question(verdict, round_), [APPROVE, CHANGES])
        if answer.strip().lower().startswith(APPROVE):
            break
        ctx.phase("changes")
        changes = await _step(
            ctx, _changes(work, answer, verdict, round_), effort="xhigh", label=f"changes {round_}"
        )
        round_, revision = round_ + 1, str(changes.value)

    ctx.phase("final render")
    final = await _step(
        ctx, _render(work, verdict, answer, round_), effort="low", label="final render"
    )
    return {
        "project": project,
        "master": final.value,
        "rounds": round_,
        "approval": answer,
        "final_review": verdict,
        "acts": [_summary(item) for item in acts],
        "next": (
            "Deliver the master with upload_files and say where it came from in one line "
            "(SKILL.md section 8, step 2); the delivery ledger records it. Helpers never deliver."
        ),
    }


async def _step(
    ctx: WorkflowContext,
    brief: str,
    *,
    effort: str,
    label: str,
    schema: Mapping[str, Any] | None = None,
) -> Step:
    """One step; a helper that fails is re-issued once under the resume preamble (SKILL.md
    section 6)."""
    try:
        return await ctx.agent(brief, effort=effort, label=label, schema=schema)
    except StepFailed as failure:
        return await ctx.agent(
            _resumed(brief, failure.reason), effort=effort, label=f"{label}, resumed", schema=schema
        )


def _label(act: Mapping[str, Any], what: str) -> str:
    return f"{act['name']}: {what}"


def _verdict(passing: str) -> str:
    """The end of a critic's brief: the JSON the pipeline reads (REVIEW_SCHEMA)."""
    return (
        "The report your brief asks for, ending with one JSON object:\n"
        f'{{"score": <1-5 overall>, "pass": <true if {passing}>, '
        '"issues": ["<each MUST-FIX note, in one line>"]}'
    )


# -- the briefs: roles, pointers to the skill's briefs, and the values to fill in -----------------


def _plan(work: str, notes: str) -> str:
    lead_notes = f"\nNOTES FROM THE LEAD\n{notes.strip()}\n" if notes.strip() else ""
    return f"""ROLE
You plan the production of the launch film in {work}/: its acts, its shared rig, and one filled builder's brief per act. You don't build. A pipeline runs your plan: the first act you list is built first, with the rig, at max effort. Then the other acts are built in parallel, each reviewed by a critic as it lands and given one fix pass if the review doesn't pass. Assembly, a final review, the person's approval and the final render follow.

READ FIRST
- {SKILL} (sections 5-7) and {ORCHESTRATION}.
- The project: BRIEF.md, storyboard/, timeline.js (frozen when the animatic was approved), STYLE.md, PLAN.md.
- The brief you fill for each act: {BRIEFS}/act-builder.md ({BRIEFS}/README.md says how).
{lead_notes}
DELIVERABLES (in the project dir)
- briefs/act-<N>.md for every act: act-builder.md's Part 1, filled, with N the act's number in film order. Give each budget as minutes from the builder's start rather than a clock time: acts start when the lead act lands, and the builder reads the clock when it begins. In section 4.3, point to API.md in the project dir, which the first act writes before any other act starts.
- PLAN.md, updated with the acts, their efforts and the build order.

REPORT
Your report, ending with one JSON object:
{{"acts": [{{"name": "Act <N>: <title>", "seconds": <length>, "effort": "max" or "xhigh", "brief": "<path of its filled brief>"}}], "rig": "<the shared systems the first act builds and proves>"}}
List the acts in build order: the system-defining act first, then the others in film order."""


def _lead(work: str, act: Mapping[str, Any], rig: str) -> str:
    return f"""ROLE
You are the lead builder of the launch film in {work}/: {act["name"]} ({act["seconds"]} s), and the shared rig: {rig}.

BRIEF
Your brief is {act["brief"]}, filled from {BRIEFS}/act-builder.md. Read it and follow it. As the lead ({SKILL} section 5):
- prove the shared rig inside your finished act;
- write API.md in the project dir from the real exports (grep -n "^export" rig/*.js timeline.js), with one-line signatures and the exact line every act uses to load the rig;
- leave the shared modules frozen: when you report, every other act's builder starts from them, in parallel.

REPORT
The report your brief asks for, and API.md's path."""


def _build(
    work: str, act: Mapping[str, Any], count: int, lead: Mapping[str, Any], lead_build: Step
) -> str:
    return f"""ROLE
You build {act["name"]} ({act["seconds"]} s) of the launch film in {work}/, one of {count} acts. The lead act, {lead["name"]}, built the shared rig and froze it; the other acts are built in parallel with yours.

BRIEF
Your brief is {act["brief"]}, filled from {BRIEFS}/act-builder.md. Read it and follow it. Read API.md in the project dir and the lead act's files before you start.

The lead builder's report:
{lead_build.value}

REPORT
The report your brief asks for. A critic reviews your act as soon as you report."""


def _review(work: str, act: Mapping[str, Any], build: Step) -> str:
    return f"""ROLE
You are the critic for {act["name"]} of the launch film in {work}/.

BRIEF
Your brief is {BRIEFS}/critic.md. Read it and follow it at this act's gate: its range in timeline.js, and its files and done-act JSON as its builder's brief ({act["brief"]}) names them.

Its builder's report, for orientation only (regenerate your own evidence):
{build.value}

REPORT
{_verdict("the act can go to assembly without a fix pass")}"""


def _fix(work: str, act: Mapping[str, Any], review: Mapping[str, Any]) -> str:
    return f"""ROLE
You make one fix pass on {act["name"]} of the launch film in {work}/, on its critic's must-fix notes.

BRIEF
This continues the act's build: read {BRIEFS}/resume.md (the resume preamble), then its brief, {act["brief"]}, filled from {BRIEFS}/act-builder.md. Everything in that brief still applies, including the files you may edit. Other acts may still be building, so the shared modules stay frozen: propose changes to them in analysis/requests/.

The critic scored the act {review["score"]}/5 (its review is in review/). Must-fix:
{_bullets(review["issues"])}

REPORT
The report your brief asks for, with what you fixed and what you couldn't."""


def _assembly(work: str, acts: Sequence[Mapping[str, Any]], round_: int, revision: str) -> str:
    changes = (
        f"\nThe person asked for changes after round {round_ - 1}; the revision pass reported:\n{revision}\n"
        if revision
        else ""
    )
    return f"""ROLE
You integrate the launch film in {work}/ (round {round_}). Every act is built and reviewed; nothing else is building.

BRIEF
Follow {SKILL} section 6 (step 2) and section 7:
1. Merge the builders' analysis/requests/* into the shared modules, with a change notice for each (the format is in {BRIEFS}/resume.md). Chain each guarded edit to its check and render with && (or set -e).
2. Make index.html mount every act (acts/act-<N>.html) on its range, then render the integration preview yourself, the way {BRIEFS}/helper.md describes (30 fps, draft quality, the film's preview blur setting, behind the render lock).
3. Run the checks in section 7: frames at every act boundary, the motion curve against the animatic, the audit, lint and loudness.

The acts:
{_bullets(_act_line(item) for item in acts)}
{changes}
REPORT
The preview's path, each check's result, what you merged, and anything that blocks the final."""


def _final_review(work: str, assembly: Step, round_: int) -> str:
    return f"""ROLE
You are the critic for the launch film in {work}/ at its final review, before the final render (round {round_}).

BRIEF
Your brief is {BRIEFS}/critic.md. Read it and follow it at the integration gate, as the film's final review: the integration preview in build/ and the project, judged against BRIEF.md, STYLE.md and the approved storyboard and animatic. Write review/REVIEW-final-{round_}.md.

The assembly's report:
{assembly.value}

REPORT
{_verdict("the film can go to the final render as it is")}"""


def _question(verdict: Mapping[str, Any], round_: int) -> str:
    notes = len(verdict["issues"])
    outcome = (
        "it passes" if verdict["pass"] else f"{notes} must-fix note{'s' if notes != 1 else ''}"
    )
    return f"Render the final? Final review, round {round_}: {verdict['score']}/5, {outcome}."


def _changes(work: str, answer: str, verdict: Mapping[str, Any], round_: int) -> str:
    return f"""ROLE
You make the person's changes to the launch film in {work}/ before its final render (round {round_}).

BRIEF
This continues the acts' builds: read {BRIEFS}/resume.md (the resume preamble, and the change notice format), then the brief of every act the changes touch (briefs/act-*.md, filled from {BRIEFS}/act-builder.md). No act is building now, so the shared modules may change too; write a change notice for each change.

The person said: {answer}

The final review (review/REVIEW-final-{round_}.md) scored the film {verdict["score"]}/5. Its must-fix notes:
{_bullets(verdict["issues"])}

REPORT
What you changed, act by act, and what you couldn't."""


def _render(work: str, verdict: Mapping[str, Any], answer: str, round_: int) -> str:
    return f"""ROLE
You render the approved launch film in {work}/.

BRIEF
Your brief is {BRIEFS}/helper.md. Read it and follow it, with:
- approved at: the final review, round {round_} ({verdict["score"]}/5), and the person's answer: {answer};
- spec: the master's size, frame rate and samples from BRIEF.md and timeline.js, and the AUDIT preset timeline.js declares ({SKILL} section 8, step 1);
- outputs: the 16:9 master; the job's name is final.

REPORT
The report your brief asks for."""


def _resumed(brief: str, reason: str) -> str:
    return f"""Your previous run on this task stopped before finishing ({reason}). Your work is intact on disk. Follow the resume preamble in {BRIEFS}/resume.md: read the progress file your brief names first, and don't redo finished milestones or recorded measurements. Everything in the original brief below still applies.

--- original brief ---
{brief}"""


def _bullets(lines: Any) -> str:
    return "\n".join(f"- {line}" for line in lines) or "- (none)"


def _act_line(item: Mapping[str, Any]) -> str:
    review, fix = item["review"], item["fix"]
    state = "passed" if fix is None else f"fixed after review by {fix.task_id}"
    return (
        f"{item['act']['name']} ({item['effort']}): built by {item['build'].task_id}, "
        f"review {review['score']}/5, {state}"
    )


def _summary(item: Mapping[str, Any]) -> dict[str, Any]:
    review = item["review"]
    return {
        "name": item["act"]["name"],
        "effort": item["effort"],
        "score": review["score"],
        "pass": review["pass"],
        "issues": list(review["issues"]),
        "fixed": item["fix"] is not None,
    }

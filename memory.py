"""MDA memory: a team layer every caller shares, and a personal layer per person.

`/memories/agent/` holds team rules (anyone who mentions the agent can add to it, so it is never a
place for private data). `/memories/user/` belongs to the verified person who asked. MDA mounts it
only for a run with a person behind it; this policy decides on which surfaces.
"""

from managed_deepagents import ManagedChannelContext, MemoryLayer, define_memory


def personal_memory_in_slack(context: object) -> bool:
    """Mount the asker's own layer anywhere in Slack, not only in their DM (MDA's default).

    People ask for work in channel threads, so their preferences have to be there too. The cost:
    their hot `AGENTS.md` is in context in a shared thread, which is why `instructions.md` says
    never to repeat it there. Only MDA's channel schema counts as proof of where a run came from.
    """
    return isinstance(context, ManagedChannelContext) and context.channel["provider"] == "slack"


memory = define_memory(agent=MemoryLayer(), user=MemoryLayer(allow=personal_memory_in_slack))

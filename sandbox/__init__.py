"""The designer's computer on Managed Deep Agents.

MDA bakes `setup.sh` on top of the base declared here and clones the result for each thread.
MDA reads this declaration statically, so every value is a literal or a top-level constant; the
`DESIGN_AGENT_SANDBOX_*` settings size local and self-hosted sandboxes, and these constants size
MDA's.

The computer unpacks to about 1.3 GiB, more than the 1 GiB filesystem MDA gives a `docker_image`
bake, so production deploys use a snapshot published from the same recipe with room for renders:

    uv run design-agent sandbox publish --fs-gib 16

`publish` rewrites BASE_IMAGE below into a snapshot declaration; until then `mda deploy` runs out of
disk baking the recipe, and `doctor` says so. Egress is default-deny; EGRESS_ALLOW lists the hosts
the sandbox may reach (none by default: host tools fetch, the sandbox does not).
"""

from managed_deepagents import define_sandbox

BASE_IMAGE = "node:22.23.3-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392"
VCPUS = 8
MEM_BYTES = 17179869184  # 16 GiB
FS_CAPACITY_BYTES = 17179869184  # 16 GiB
IDLE_TTL_SECONDS = 600
DEFAULT_TIMEOUT_SECONDS = 1800
EGRESS_ALLOW: list[str] = []

sandbox = define_sandbox(
    docker_image=BASE_IMAGE,
    idle_ttl_seconds=IDLE_TTL_SECONDS,
    default_timeout=DEFAULT_TIMEOUT_SECONDS,
    proxy_config={"access_control": {"allow_list": EGRESS_ALLOW}},
    vcpus=VCPUS,
    mem_bytes=MEM_BYTES,
    fs_capacity_bytes=FS_CAPACITY_BYTES,
)

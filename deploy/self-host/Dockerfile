# The self-hosted agent: the HTTP API and the Slack adapter run from this image. Renders run in
# separate sandbox containers (sandbox/Dockerfile) that the agent starts through the Docker socket.
FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv
FROM docker:27.5.1-cli@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c AS docker-cli

FROM python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra self-host --extra slack
COPY instructions.md NOTICE.md ./
COPY config ./config
COPY skills ./skills
COPY skill-binaries ./skill-binaries
COPY workspace/tools ./workspace/tools
COPY examples/brands ./examples/brands
COPY fonts ./fonts
COPY licenses ./licenses
COPY sandbox ./sandbox
RUN useradd --create-home --uid 10001 agent && mkdir -p /app/workspace/out /app/workspace/state && chown -R agent /app/workspace
USER agent
ENV DESIGN_AGENT_RUNTIME=self_hosted DESIGN_AGENT_API_HOST=0.0.0.0
EXPOSE 8080
CMD ["design-agent", "serve"]

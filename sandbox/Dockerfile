# The designer's computer as an image: the published-snapshot path, the local Docker sandbox
# runner and CI all build this file, which only runs the same recipe MDA bakes.
# Build: docker build -t design-agent-sandbox sandbox/  (linux/amd64 and linux/arm64)
FROM node:22.23.3-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
COPY setup.sh /tmp/design-agent-setup.sh
RUN bash /tmp/design-agent-setup.sh && rm /tmp/design-agent-setup.sh
# Upstream tools that report usage honor these; the sandbox has no egress either way.
ENV DO_NOT_TRACK=1 HYPERFRAMES_NO_TELEMETRY=1
WORKDIR /workspace
CMD ["sleep", "infinity"]

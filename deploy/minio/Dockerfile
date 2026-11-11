# Build official community releases from immutable upstream commits.
FROM golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb AS build
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
RUN go install github.com/minio/minio@9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a
RUN go install github.com/minio/mc@d6541ea280b73a834b64d4097e21f2be77676104
RUN cp "$(go list -m -f '{{.Dir}}' github.com/minio/minio@9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a)/LICENSE" /go/bin/MINIO-LICENSE \
    && cp "$(go list -m -f '{{.Dir}}' github.com/minio/mc@d6541ea280b73a834b64d4097e21f2be77676104)/LICENSE" /go/bin/MC-LICENSE

FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home minio && mkdir /data && chown minio /data
COPY --from=build /go/bin/minio /go/bin/mc /usr/local/bin/
COPY --from=build /go/bin/MINIO-LICENSE /go/bin/MC-LICENSE /usr/share/doc/minio/
COPY deploy/minio/init.sh deploy/minio/run.sh deploy/minio/app-policy.json /opt/minio/
USER minio
EXPOSE 9000 9001
ENTRYPOINT ["/bin/sh", "/opt/minio/run.sh"]
CMD ["server", "/data", "--console-address", ":9001"]

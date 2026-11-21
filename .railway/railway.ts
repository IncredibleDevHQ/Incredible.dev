import { defineRailway, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const region = "us-east4-eqdc4a";
  const objects = volume("minio-data", { region, sizeMB: 10240 });
  const workspace = volume("workspace", { region, sizeMB: 5120 });
  const minio = service("minio", {
    build: { builder: "DOCKERFILE", dockerfilePath: "deploy/minio/Dockerfile" },
    start: "/bin/sh /opt/minio/railway.sh",
    healthcheck: "/minio/health/ready",
    healthcheckTimeout: 120,
    replicas: { [region]: 1 },
    deploy: { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 5 },
    volumeMounts: { "/data": objects },
    env: {
      PORT: "9000",
      RAILWAY_RUN_UID: "0",
      MINIO_ROOT_USER: preserve(),
      MINIO_ROOT_PASSWORD: preserve(),
      DESIGN_AGENT_S3_ACCESS_KEY: preserve(),
      DESIGN_AGENT_S3_SECRET_KEY: preserve(),
    },
  });
  const web = service("web", {
    // Deploy the reviewed checkout with railway up. Staging can use an unmerged branch.
    build: { builder: "DOCKERFILE", dockerfilePath: "deploy/local/Dockerfile" },
    start: "python -I deploy/railway/start.py",
    healthcheck: "/healthz",
    healthcheckTimeout: 120,
    replicas: { [region]: 1 },
    deploy: { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 5 },
    volumeMounts: { "/data": workspace },
    env: {
      RAILWAY_RUN_UID: "0",
      DESIGN_AGENT_RUNTIME: "local",
      DESIGN_AGENT_SANDBOX: "docker",
      DESIGN_AGENT_WORKSPACE_ROOT: "/data/workspace",
      DESIGN_AGENT_AUTH_REQUIRED: "1",
      DESIGN_AGENT_ENABLE_TRACES: "0",
      DESIGN_AGENT_BLOB_BACKEND: "s3",
      DESIGN_AGENT_BLOB_S3_ADDRESSING_STYLE: "path",
      DESIGN_AGENT_S3_ENDPOINT: "http://minio.railway.internal:9000",
      DESIGN_AGENT_S3_BUCKET: "incredible-files",
      DESIGN_AGENT_S3_REGION: "us-east-1",
      DESIGN_AGENT_S3_ACCESS_KEY: minio.env.DESIGN_AGENT_S3_ACCESS_KEY,
      DESIGN_AGENT_S3_SECRET_KEY: minio.env.DESIGN_AGENT_S3_SECRET_KEY,
      DESIGN_AGENT_APP_URL: preserve(),
      SUPABASE_URL: preserve(),
      SUPABASE_PUBLISHABLE_KEY: preserve(),
      DATABASE_URL: preserve(),
      DESIGN_AGENT_MODEL: preserve(),
      OPENAI_API_KEY: preserve(),
      ANTHROPIC_API_KEY: preserve(),
      MOONSHOT_API_KEY: preserve(),
      DESIGN_AGENT_RESEARCH_CATALOG_DIR: preserve(),
      DESIGN_AGENT_RESEARCH_OWNER_ID: preserve(),
      DESIGN_AGENT_RESEARCH_READER_CONTAINER: preserve(),
      DESIGN_AGENT_SANDBOX_IMAGE: preserve(),
      DOCKER_HOST: preserve(),
      RUNNER_CA_PEM: preserve(),
      RUNNER_CERT_PEM: preserve(),
      RUNNER_KEY_PEM: preserve(),
    },
  });
  return project("incredible", { resources: [web, minio, workspace, objects] });
});

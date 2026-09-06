# Production deployment

- Deploy production exclusively through the GitHub Actions **Build, Test and
  Deploy** workflow from `main`.
- Never bypass that workflow with a manual SSH deployment, build production
  images on the VPS, or copy a repository checkout/application source tree there.
- The VPS receives GHCR images and only the minimal deployment artifacts already
  uploaded by the workflow (Compose, deployment scripts and runtime configuration).
- SSH may be used for diagnostics and authorized operational cleanup. Do not
  interpret SSH access as permission to use a different deployment method.
- The home Tinyproxy service is separate infrastructure; preserve its operation
  when working on local development services or deploying the VPS backend.

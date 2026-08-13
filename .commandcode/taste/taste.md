# Taste

See [taste/taste.md](taste/taste.md)

## Tooling / environment
- For standing up local infrastructure for live testing (local Opik, Postgres), prefers docker-compose over a manually-typed `docker run` command or installing the service natively — expects the agent to add the docker-compose service to the repo, boot it, and verify the UI/endpoint actually responds before testing against it. Confidence: 0.55

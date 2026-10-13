# Here are your Instructions

## Deploy with Docker

Images are built by GitHub Actions (`.github/workflows/docker-publish.yml`) on every push to `main` and pushed to Docker Hub as
`<repo>:backend-latest` and `<repo>:frontend-latest` (also `-<sha>` and `-<version>` tags).
Repository secrets required: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`. Optional repository variable `IMAGE_REPO` overrides the default `<username>/governance`.

On the server:

```
git clone <this repo> && cd governance_platform     # or copy docker-compose.yml and .env.example only
cp .env.example .env                                 # set EDGE_SIGNING_SECRET, BOOTSTRAP_ADMIN_TOKEN, CORS_ORIGINS, IMAGE_REPO
docker compose pull && docker compose up -d
```

Open `http://<server>:5021/`, sign in with the `BOOTSTRAP_ADMIN_TOKEN`, then add people under People & Teams.
Update: `docker compose pull && docker compose up -d`. Back up the `mongo_data` volume.
Outbound network use: `git clone` of audited repositories, and model providers only if API keys are set and Zero-LLM is off.

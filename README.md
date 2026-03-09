# dev.events MCP Server + Web App

MCP server that fetches tech conference data from [dev.events](https://dev.events/), with a web frontend and MCP gateway.

## Architecture

```text
Browser :8080  <-->  Gateway (FastAPI)  <-->  MCP Server (SSE :8000)
                     REST API + static        dev.events scraper
```

## Tools

| Tool | Description |
|---|---|
| `get_events` | Fetch conferences. Filters: `topic`, `region` (EU/NA/AS/AF/SA/OC/ON), `country` (2-letter code), `city`, `start_date`, `end_date`, `limit`. |
| `get_event_details` | Get details for a specific event by its URL slug. |

## Web App (Docker Compose)

```bash
docker compose up --build
```

Open <http://localhost:8080> — filter by topic, region, country, city, and date range.

## MCP Server Only

Build:

```bash
docker build -t dev-events-mcp .
```

Run standalone (stdio):

```bash
docker run -i dev-events-mcp
```

Run with SSE transport:

```bash
docker run -e MCP_TRANSPORT=sse -p 8000:8000 dev-events-mcp
```

## Use in cagent

```yaml
toolsets:
  - type: mcp
    ref: dev-events-mcp
```

## Run locally (without Docker)

```bash
pip install -r requirements.txt
python server.py
```

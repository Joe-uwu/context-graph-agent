# Cortex dashboard

A single-file operational console for the context graph — "Datadog meets Glean". It is a
static SPA (`index.html`): React is loaded from a CDN, so there is no build step, and it
talks to `api-service` over REST from the browser.

## Views

| View | Source |
| --- | --- |
| Risk Dashboard | `GET /api/v1/risk/top` — entities ranked by cross-source urgency + the headline interrupt |
| Notification Feed | `GET /api/v1/notifications` — bundled, grounded, de-duplicated alerts |
| Incident Explorer | incidents and their blast radius across the graph |
| Live Event Stream | source events flowing through the pipeline |
| Graph & Relationship Explorer | force-directed neighborhood with a relationship-type filter |
| Entity Inspector | `GET /api/v1/graph/nodes/{id}` — properties, urgency features, relationships |
| Search | `POST /api/v1/search` — hybrid graph + vector search |
| Timeline Replay | scrub the incident forward and watch the picture assemble |

## Run

It ships with an embedded demo dataset (the "deploy will fail" scenario), so it renders
with **no backend** — open `index.html` directly, or:

```bash
docker build -t cortex/dashboard apps/dashboard
docker run -p 3000:3000 cortex/dashboard        # http://localhost:3000
```

Toggle **Demo → Live** in the top bar (and set the api base URL, default
`http://localhost:8000`) to read the running `api-service` instead of the demo data. The
full stack (`make up`) brings up the dashboard alongside the API.

CORS is enabled on every service (`cortex.platform.http.create_base_app`) so the browser
can call the API cross-origin.

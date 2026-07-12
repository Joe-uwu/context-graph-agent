# Cortex dashboard

Next.js (App Router) + TypeScript. Reads only through `api-service`.

```bash
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

Run `uvicorn cortex.services.api.server:app` first so the API is serving the live
in-memory pipeline. The overview page renders the ranked risks and the proactive
notifications the graph produced. The graph explorer (React Flow over
`/api/v1/graph/nodes/{id}/neighborhood`) and risk analytics (Recharts) mount into the
same shell; this scaffold ships the overview and the API client they build on.

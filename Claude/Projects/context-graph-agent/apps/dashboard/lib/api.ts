// Thin client for the Cortex API. The dashboard reads only through api-service.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ORG = process.env.NEXT_PUBLIC_ORG_ID ?? "org_demo";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "x-org-id": ORG },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  const body = await res.json();
  return body.data as T;
}

export type RiskNode = {
  id: string;
  label: string;
  display: string;
  urgency: number;
  features: Record<string, number>;
};

export type Notification = {
  id: string;
  node_id: string;
  channel: string;
  title: string;
  body: string;
  risk_score: number;
  confidence: number;
  recipients: string[];
};

export const api = {
  topRisks: () => get<RiskNode[]>("/api/v1/risk/top?limit=10&min_score=0.1"),
  notifications: () => get<Notification[]>("/api/v1/notifications"),
};

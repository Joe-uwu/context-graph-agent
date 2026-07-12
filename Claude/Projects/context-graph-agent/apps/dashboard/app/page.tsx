// Overview page: the ranked risks and the proactive notifications the graph produced.
// Server component — fetches from api-service on each request.
import { api, type Notification, type RiskNode } from "../lib/api";

const card = {
  background: "#14171c",
  border: "1px solid #232830",
  borderRadius: 12,
  padding: 20,
};

function scoreColor(s: number): string {
  if (s >= 0.75) return "#ff5c5c";
  if (s >= 0.6) return "#ffb020";
  return "#5c9bff";
}

async function safe<T>(p: Promise<T>, fallback: T): Promise<T> {
  try {
    return await p;
  } catch {
    return fallback;
  }
}

export default async function Overview() {
  const [risks, notifications] = await Promise.all([
    safe<RiskNode[]>(api.topRisks(), []),
    safe<Notification[]>(api.notifications(), []),
  ]);

  return (
    <main style={{ display: "grid", gap: 24, gridTemplateColumns: "1fr 1fr" }}>
      <section style={card}>
        <h2 style={{ marginTop: 0, fontSize: 16 }}>Critical issues</h2>
        {notifications.length === 0 && (
          <p style={{ color: "#8b93a1" }}>Nothing above the interrupt bar. All quiet.</p>
        )}
        {notifications.map((n) => (
          <article key={n.id} style={{ marginBottom: 16, paddingBottom: 16, borderBottom: "1px solid #232830" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong>{n.title}</strong>
              <span style={{ color: scoreColor(n.risk_score), fontVariantNumeric: "tabular-nums" }}>
                {n.risk_score.toFixed(2)}
              </span>
            </div>
            <p style={{ color: "#c3c9d2", fontSize: 14, lineHeight: 1.5 }}>{n.body}</p>
            <div style={{ color: "#8b93a1", fontSize: 12 }}>
              {n.channel} · confidence {n.confidence.toFixed(2)} · → {n.recipients.join(", ")}
            </div>
          </article>
        ))}
      </section>

      <section style={card}>
        <h2 style={{ marginTop: 0, fontSize: 16 }}>Top risks</h2>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <tbody>
            {risks.map((r) => (
              <tr key={r.id} style={{ borderBottom: "1px solid #232830" }}>
                <td style={{ padding: "8px 0", color: scoreColor(r.urgency), width: 48, fontVariantNumeric: "tabular-nums" }}>
                  {r.urgency.toFixed(2)}
                </td>
                <td style={{ color: "#8b93a1", width: 90 }}>{r.label}</td>
                <td>{r.display}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p style={{ color: "#6b7280", fontSize: 12, marginTop: 16 }}>
          The graph explorer (React Flow) and analytics (Recharts) mount here; this overview
          reads the live api-service.
        </p>
      </section>
    </main>
  );
}

import type { ReactNode } from "react";

export const metadata = {
  title: "Cortex",
  description: "Proactive enterprise context graph",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          background: "#0b0d10",
          color: "#e6e8eb",
          fontFamily: "ui-sans-serif, system-ui, -apple-system, sans-serif",
        }}
      >
        <div style={{ maxWidth: 1100, margin: "0 auto", padding: "32px 24px" }}>
          <header style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 28 }}>
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>Cortex</h1>
            <span style={{ color: "#8b93a1", fontSize: 14 }}>
              proactive enterprise context graph
            </span>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}

import { cellStyle, isRisk, RISK, STATUS_LV, type Bucket } from "../risk";

/** A risk level as colour + icon + word (never colour alone). */
export function RiskPill({ risk, prefix }: { risk: string | null | undefined; prefix?: string }) {
  if (!isRisk(risk)) return null;
  const r = RISK[risk];
  return (
    <span className="risk-pill" style={{ background: r.color, color: r.text }} title={`Risks: ${r.label}`}>
      <span aria-hidden>{r.icon}</span>
      {prefix ? `${prefix} ` : ""}
      {r.label}
    </span>
  );
}

/** One module's status and risk in a table cell (not applicable: grey, no risk). */
export function StatusCell({ bucket, risk }: { bucket: Bucket; risk: string | null }) {
  const s = cellStyle(bucket, risk);
  const text = bucket === "not_applicable" ? STATUS_LV[bucket] : `${STATUS_LV[bucket]} · ${s.label}`;
  return (
    <span className="cell" style={{ background: s.color, color: s.text }} title={text}>
      <span aria-hidden>{s.icon}</span>
      {text}
    </span>
  );
}

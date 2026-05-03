import type { ClusterRiskRow } from "@/lib/api";

function clusterFill(label: string | null): string {
  if (!label) return "#94a3b8";
  const l = label.toLowerCase();
  if (/coaliz[aã]o\s+govern/.test(l)) return "#1B4332";
  if (/centr[aã]o/.test(l))           return "#C17D3C";
  if (/bolsonar/.test(l))             return "#1A1F2E";
  return "#94a3b8";
}

export default function ConstitutionalRiskByCluster({
  rows,
}: {
  rows: ClusterRiskRow[];
}) {
  if (rows.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-concreto-shadow p-8 text-center">
        <p className="text-text-warm">Sem dados de risco constitucional por coalizão.</p>
      </div>
    );
  }

  // Worst-offender for the insight copy below the chart.
  const worst = [...rows]
    .filter((r) => r.pct_yes_on_high_risk != null)
    .sort((a, b) => (b.pct_yes_on_high_risk! - a.pct_yes_on_high_risk!))[0];

  return (
    <div className="space-y-5">
      <div className="bg-white rounded-lg border border-concreto-shadow shadow-sm p-5 sm:p-6 space-y-5">
        {rows.map((r) => {
          const color = clusterFill(r.cluster);
          const pct = r.pct_yes_on_high_risk ?? 0;
          // Bar colour: cluster colour by default, but high-rate (>50%)
          // gets a warm-red overlay so the eye lands on the danger row.
          const overlay = pct > 50 ? "#C0392B" : color;
          const avgRiskPct = r.avg_bill_risk != null ? Math.round(r.avg_bill_risk * 100) : null;

          return (
            <div key={r.cluster_id}>
              <div className="flex items-baseline justify-between gap-2 mb-1.5 flex-wrap">
                <p className="font-display font-bold text-brasilia text-sm">
                  {r.cluster ?? "Sem cluster"}
                </p>
                <p className="text-[11px] text-text-warm font-mono">
                  {r.deputy_count} dep · coesão {(r.cohesion_score ?? 0).toFixed(2)}
                  {avgRiskPct != null && (
                    <> · risco médio dos projetos votados {avgRiskPct}%</>
                  )}
                </p>
              </div>
              <div className="relative h-7 bg-concreto-shadow rounded-md overflow-hidden">
                <div
                  className="absolute inset-y-0 left-0 transition-[width]"
                  style={{ width: `${pct}%`, backgroundColor: overlay }}
                />
                <div className="absolute inset-0 flex items-center justify-between px-3">
                  <span
                    className={`text-xs font-mono font-semibold ${pct > 22 ? "text-white" : "text-brasilia"}`}
                  >
                    {Math.round(pct)}% sim em alto risco
                  </span>
                  <span className="text-[10px] text-text-warm/90 font-mono">
                    {r.high_risk_bills_voted} projetos
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {worst && (
        <article className="bg-white rounded-lg border border-concreto-shadow border-l-[4px] border-l-[#C0392B] p-4 text-sm leading-relaxed">
          <p className="text-brasilia">
            A coalizão que mais votou a favor de projetos com{" "}
            <strong>alto risco constitucional</strong> foi o{" "}
            <strong className="text-brasilia">{worst.cluster}</strong> —
            aprovando{" "}
            <span className="font-mono font-semibold">
              {Math.round(worst.pct_yes_on_high_risk ?? 0)}%
            </span>{" "}
            dos projetos sinalizados como potencialmente inconstitucionais (em{" "}
            <span className="font-mono">{worst.high_risk_bills_voted}</span>{" "}
            proposições analisadas).
          </p>
        </article>
      )}
    </div>
  );
}

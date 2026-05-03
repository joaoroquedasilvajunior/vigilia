import type { ClusterRiskRow } from "@/lib/api";

function clusterFill(label: string | null): string {
  if (!label) return "#94a3b8";
  const l = label.toLowerCase();
  if (/coaliz[aã]o\s+govern/.test(l)) return "#1B4332";
  if (/centr[aã]o/.test(l))           return "#C17D3C";
  if (/bolsonar/.test(l))             return "#1A1F2E";
  return "#94a3b8";
}

// Population-mean reference for the "everyone votes ~75% sim" headline.
// Computed per-render rather than hardcoded so the line tracks reality if
// the cluster mix shifts.
function meanPctYes(rows: ClusterRiskRow[]): number | null {
  const vals = rows
    .map((r) => r.pct_yes_on_high_risk)
    .filter((v): v is number => v != null);
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

export default function ConstitutionalRiskByCluster({
  rows,
}: {
  rows: ClusterRiskRow[];
}) {
  if (rows.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-concreto-shadow p-8 text-center">
        <p className="text-text-warm">
          Sem dados de risco constitucional por coalizão.
        </p>
      </div>
    );
  }

  const meanPct = meanPctYes(rows);

  return (
    <div className="space-y-5">
      <div className="bg-white rounded-lg border border-concreto-shadow shadow-sm p-5 sm:p-6 space-y-6">
        {rows.map((r) => {
          const color = clusterFill(r.cluster);
          const pctYes = r.pct_yes_on_high_risk ?? 0;
          // const_alignment_score is on a -1..+1 scale. We display its
          // *positive* magnitude as a bar from 0 to 100 (alignment score
          // 1.0 → full bar) but show the signed value in the label so the
          // sign is preserved. This is the cluster-differentiating metric
          // — the sim-rate one barely differs across coalitions.
          const align = r.avg_alignment ?? 0;
          const alignBarPct = Math.min(100, Math.max(0, Math.abs(align) * 100));
          const alignSign = align >= 0;

          return (
            <div key={r.cluster_id}>
              <div className="flex items-baseline justify-between gap-2 mb-2 flex-wrap">
                <p className="font-display font-bold text-brasilia text-sm">
                  {r.cluster ?? "Sem cluster"}
                </p>
                <p className="text-[11px] text-text-warm font-mono">
                  {r.deputy_count} dep · coesão{" "}
                  {(r.cohesion_score ?? 0).toFixed(2)} ·{" "}
                  {r.high_risk_bills_voted} projetos de alto risco votados
                </p>
              </div>

              {/* Bar 1: % sim em alto risco */}
              <div className="space-y-1.5">
                <div className="flex items-center gap-2 text-[10px] text-text-warm font-mono uppercase tracking-wider">
                  <span className="w-44 shrink-0">% sim em alto risco</span>
                </div>
                <div className="relative h-6 bg-concreto-shadow rounded-md overflow-hidden">
                  <div
                    className="absolute inset-y-0 left-0 transition-[width]"
                    style={{ width: `${pctYes}%`, backgroundColor: color }}
                  />
                  {/* Reference line at the across-cluster mean ("média geral") */}
                  {meanPct != null && (
                    <div
                      className="absolute top-0 bottom-0 border-l-2 border-dashed border-ipe"
                      style={{ left: `${meanPct}%` }}
                      title={`média geral: ${meanPct.toFixed(1)}%`}
                    />
                  )}
                  <div className="absolute inset-0 flex items-center px-3">
                    <span
                      className={`text-xs font-mono font-semibold ${pctYes > 22 ? "text-white" : "text-brasilia"}`}
                    >
                      {Math.round(pctYes)}%
                    </span>
                  </div>
                </div>
              </div>

              {/* Bar 2: alinhamento médio com a CF/88 */}
              <div className="space-y-1.5 mt-2">
                <div className="flex items-center gap-2 text-[10px] text-text-warm font-mono uppercase tracking-wider">
                  <span className="w-44 shrink-0">alinhamento médio CF/88</span>
                </div>
                <div className="relative h-6 bg-concreto-shadow rounded-md overflow-hidden">
                  <div
                    className="absolute inset-y-0 left-0 transition-[width]"
                    style={{
                      width: `${alignBarPct}%`,
                      backgroundColor: alignSign ? color : "#C0392B",
                      opacity: 0.85,
                    }}
                  />
                  <div className="absolute inset-0 flex items-center px-3">
                    <span
                      className={`text-xs font-mono font-semibold ${alignBarPct > 22 ? "text-white" : "text-brasilia"}`}
                    >
                      {alignSign ? "+" : ""}
                      {align.toFixed(2)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}

        {/* Legend explaining the dashed reference line */}
        {meanPct != null && (
          <div className="pt-3 mt-2 border-t border-concreto-shadow flex items-center gap-2 text-[11px] text-text-warm">
            <span
              className="inline-block w-4 h-0 border-t-2 border-dashed border-ipe"
              aria-hidden
            />
            <span>
              média geral entre coalizões:{" "}
              <span className="font-mono font-semibold text-brasilia">
                {meanPct.toFixed(1)}%
              </span>
            </span>
          </div>
        )}
      </div>

      <article className="bg-white rounded-lg border border-concreto-shadow border-l-[4px] border-l-ochre p-4 text-sm text-brasilia leading-relaxed">
        <p>
          Independentemente da coalizão, os deputados votam a favor de
          projetos com <strong>alto risco constitucional</strong> em
          aproximadamente <span className="font-mono font-semibold">75%</span>{" "}
          das vezes. Isso sugere que projetos polêmicos só chegam ao plenário
          quando já têm maioria garantida — o filtro não é ideológico, é
          numérico.
        </p>
        <p className="mt-2 text-xs text-text-warm">
          A diferenciação real entre coalizões aparece no{" "}
          <strong>alinhamento médio com a CF/88</strong> dos próprios
          deputados (segunda barra de cada linha) — métrica que combina
          sentido do voto, gravidade do risco do projeto e direção do
          posicionamento partidário.
        </p>
      </article>
    </div>
  );
}

import Link from "next/link";
import type { UrgencyResponse, UrgencyAggregate } from "@/lib/api";

function fmtBR(n: number): string {
  return new Intl.NumberFormat("pt-BR").format(n);
}

function StatCard({
  title,
  agg,
  tone,
}: {
  title: string;
  agg: UrgencyAggregate | null;
  tone: "neutral" | "warn";
}) {
  const ring =
    tone === "warn"
      ? "border-l-[4px] border-l-[#C0392B]"
      : "border-l-[4px] border-l-cerrado";
  if (!agg) {
    return (
      <article className={`bg-white rounded-lg border border-concreto-shadow ${ring} p-5`}>
        <p className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
          {title}
        </p>
        <p className="text-text-warm text-sm mt-2">Sem dados.</p>
      </article>
    );
  }
  const avgRiskPct = agg.avg_risk != null ? Math.round(agg.avg_risk * 100) : null;
  return (
    <article className={`bg-white rounded-lg border border-concreto-shadow ${ring} p-5`}>
      <p className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
        {title}
      </p>
      <p className="font-mono text-3xl font-bold text-brasilia mt-1">
        {fmtBR(agg.bill_count)}
        <span className="text-xs text-text-warm font-normal font-sans ml-1.5">
          projetos votados
        </span>
      </p>
      <dl className="mt-4 space-y-1.5 text-sm">
        <div className="flex items-baseline justify-between">
          <dt className="text-text-warm">Risco constitucional médio</dt>
          <dd className="font-mono font-semibold text-brasilia">
            {avgRiskPct != null ? `${avgRiskPct}%` : "—"}
          </dd>
        </div>
        <div className="flex items-baseline justify-between">
          <dt className="text-text-warm">Alto risco</dt>
          <dd className="font-mono font-semibold text-brasilia">
            {agg.pct_high_risk != null ? `${Math.round(agg.pct_high_risk)}%` : "—"}
            <span className="text-text-warm/70 font-normal ml-1.5">
              ({fmtBR(agg.high_risk_count)})
            </span>
          </dd>
        </div>
      </dl>
    </article>
  );
}

export default function UrgencyRegime({ data }: { data: UrgencyResponse }) {
  const diff = data.risk_diff_pct;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_1fr_minmax(0,1.2fr)] gap-4 items-stretch">
        <StatCard title="Sem urgência" agg={data.without_urgency} tone="neutral" />
        <StatCard title="Com urgência" agg={data.with_urgency} tone="warn" />

        {/* High-risk-urgency list (right panel) */}
        <article className="bg-white rounded-lg border border-concreto-shadow shadow-sm overflow-hidden flex flex-col">
          <header className="px-4 py-3 border-b border-concreto-shadow bg-concreto-shadow/40">
            <p className="text-[10px] font-display font-bold text-brasilia uppercase tracking-widest">
              Projetos de alto risco votados em urgência
            </p>
          </header>
          <ul className="overflow-y-auto" style={{ maxHeight: 260 }}>
            {data.high_risk_urgency_bills.length === 0 ? (
              <li className="px-4 py-6 text-sm text-text-warm italic">
                Nenhum projeto de alto risco votado em urgência foi encontrado.
              </li>
            ) : (
              data.high_risk_urgency_bills.map((b) => {
                const score = b.const_risk_score ?? 0;
                return (
                  <li
                    key={b.id}
                    className="border-b border-concreto-shadow last:border-b-0"
                  >
                    <Link
                      href={`/projetos/${b.id}`}
                      className="flex items-start gap-3 px-4 py-2.5 hover:bg-concreto transition-colors group"
                    >
                      <span
                        className="shrink-0 mt-0.5 inline-flex items-center text-[10px] font-mono font-bold px-1.5 py-0.5 rounded"
                        style={{
                          backgroundColor: "#C0392B",
                          color: "white",
                        }}
                        title={`Risco constitucional: ${score.toFixed(2)}`}
                      >
                        RISCO {score.toFixed(2)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-mono text-text-warm">
                          {b.type} {b.number}/{b.year}
                        </p>
                        <p className="text-sm text-brasilia line-clamp-2 mt-0.5 group-hover:text-cerrado transition-colors">
                          {b.title}
                        </p>
                      </div>
                    </Link>
                  </li>
                );
              })
            )}
          </ul>
        </article>
      </div>

      <article className="bg-white rounded-lg border border-concreto-shadow border-l-[4px] border-l-ochre p-4 text-sm text-brasilia leading-relaxed">
        {diff != null && diff !== 0 ? (
          <>
            Projetos votados em regime de urgência têm risco constitucional médio{" "}
            <strong className="font-mono">
              {diff > 0 ? "+" : ""}
              {Math.round(diff)}%
            </strong>{" "}
            {diff > 0 ? "maior" : "menor"} do que projetos votados em
            tramitação normal. O regime de urgência reduz o tempo de análise
            e debate, o que pode aumentar o risco de inconstitucionalidades.
          </>
        ) : (
          <>
            O regime de urgência reduz o tempo de análise e debate de uma
            proposição. Quando aplicado a projetos com alto potencial de
            impacto constitucional, dificulta a fiscalização tanto da
            sociedade civil quanto da própria Câmara.
          </>
        )}
      </article>
    </div>
  );
}

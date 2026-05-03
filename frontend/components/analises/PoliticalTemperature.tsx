import Link from "next/link";
import type { PoliticalTemperatureResponse, RecentBill } from "@/lib/api";

function fmtBR(n: number): string {
  return new Intl.NumberFormat("pt-BR").format(n);
}

function fmtRelative(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days <= 0) return "hoje";
  if (days === 1) return "ontem";
  if (days < 7) return `${days} dias atrás`;
  if (days < 30) return `${Math.floor(days / 7)} sem. atrás`;
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

function StatTile({
  emoji,
  label,
  value,
  caption,
  bg,
}: {
  emoji: string;
  label: string;
  value: string;
  caption: string;
  bg: string;          // tailwind bg utility
}) {
  return (
    <article className={`${bg} rounded-lg border border-concreto-shadow p-4`}>
      <p className="flex items-center gap-1.5">
        <span aria-hidden className="text-lg leading-none">{emoji}</span>
        <span className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
          {label}
        </span>
      </p>
      <p className="font-mono text-3xl font-bold text-brasilia mt-1.5 leading-none">
        {value}
      </p>
      <p className="text-[11px] text-text-warm mt-1">{caption}</p>
    </article>
  );
}

function RecentBillRow({ b }: { b: RecentBill }) {
  const score = b.const_risk_score;
  return (
    <li className="border-b border-concreto-shadow last:border-b-0">
      <Link
        href={`/projetos/${b.id}`}
        className="flex items-start gap-3 p-3 sm:p-4 hover:bg-concreto/40 transition-colors group"
      >
        {/* Risk badge */}
        {score != null && (
          <span
            className="shrink-0 mt-0.5 inline-flex items-center text-[10px] font-mono font-bold px-1.5 py-0.5 rounded"
            style={{
              backgroundColor:
                score > 0.6 ? "#C0392B" : score >= 0.3 ? "#E8B84B" : "#1B4332",
              color: "white",
            }}
            title={`Risco constitucional: ${score.toFixed(2)}`}
          >
            {score.toFixed(2)}
          </span>
        )}
        <div className="flex-1 min-w-0">
          <p className="text-xs font-mono text-text-warm">
            {b.type} {b.number}/{b.year}
            {b.urgency_regime && (
              <span className="ml-1.5 text-[10px] uppercase tracking-wider text-ochre font-semibold">
                · urgência
              </span>
            )}
          </p>
          <p className="text-sm text-brasilia mt-0.5 line-clamp-2 group-hover:text-cerrado transition-colors">
            {b.title}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[10px] text-text-warm font-mono">
            {fmtRelative(b.last_vote)}
          </p>
          <p className="text-[10px] text-text-warm/70">
            {fmtBR(b.vote_count)} votos
          </p>
        </div>
      </Link>
    </li>
  );
}

export default function PoliticalTemperature({
  data,
}: {
  data: PoliticalTemperatureResponse;
}) {
  // Stat-card backgrounds: warm orange when urgency count exceeds 20,
  // warm red when high-risk in progress > 5. Otherwise neutral concreto.
  const urgencyBg =
    data.bills_in_urgency_now > 20 ? "bg-ochre/10" : "bg-white";
  const riskBg =
    data.high_risk_in_progress > 5 ? "bg-[#C0392B]/10" : "bg-white";

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          emoji="🔥"
          label="Em urgência"
          value={fmtBR(data.bills_in_urgency_now)}
          caption="projetos em tramitação"
          bg={urgencyBg}
        />
        <StatTile
          emoji="⚠️"
          label="Alto risco"
          value={fmtBR(data.high_risk_in_progress)}
          caption="em tramitação agora"
          bg={riskBg}
        />
        <StatTile
          emoji="📊"
          label="Votos / 30 dias"
          value={fmtBR(data.votes_last_30d)}
          caption="atividade parlamentar"
          bg="bg-white"
        />
        <StatTile
          emoji="🤝"
          label="Coalizões ativas"
          value={fmtBR(data.active_coalitions)}
          caption="clusters comportamentais"
          bg="bg-white"
        />
      </div>

      <div className="bg-white rounded-lg border border-concreto-shadow shadow-sm overflow-hidden">
        <header className="px-4 py-3 border-b border-concreto-shadow bg-concreto-shadow/40 flex items-baseline justify-between gap-2 flex-wrap">
          <p className="text-[10px] font-display font-bold text-brasilia uppercase tracking-widest">
            Projetos mais ativos recentemente
          </p>
          <p className="text-[10px] text-text-warm">
            últimos 90 dias
          </p>
        </header>
        <ul>
          {data.recent_bills.length === 0 ? (
            <li className="p-6 text-center text-sm text-text-warm italic">
              Sem atividade legislativa registrada nos últimos 90 dias.
            </li>
          ) : (
            data.recent_bills.map((b) => <RecentBillRow key={b.id} b={b} />)
          )}
        </ul>
      </div>

      <p className="text-[11px] text-text-warm/80 italic">
        Dados sincronizados diariamente às 03:00 BRT com a API da Câmara dos
        Deputados.
      </p>
    </div>
  );
}

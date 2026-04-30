import type { Metadata } from "next";
import { getLegislator, getLegislatorVotes, getClusters } from "@/lib/api";
import { notFound } from "next/navigation";
import Link from "next/link";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  try {
    const [leg, votesData, clustersData] = await Promise.all([
      getLegislator(id),
      getLegislatorVotes(id, 1).catch(() => ({ total: 0, items: [] as never[] })),
      getClusters().catch(() => ({ clusters: [] as never[] })),
    ]);
    const name = leg.display_name ?? leg.name;
    const cluster = leg.behavioral_cluster_id
      ? clustersData.clusters.find((c) => c.id === leg.behavioral_cluster_id)
      : null;
    const align =
      leg.const_alignment_score !== null
        ? leg.const_alignment_score.toFixed(2)
        : "—";
    const desc = `Deputado Federal por ${leg.state_uf} (${
      leg.party_acronym ?? "sem partido"
    }). ${votesData.total} votações registradas. Coalizão: ${
      cluster?.label ?? "—"
    }. Alinhamento CF/88: ${align}.`;
    return {
      title: name,
      description: desc,
      openGraph: {
        type: "profile",
        title: `${name} — Vigília`,
        description: desc,
        images: leg.photo_url
          ? [{ url: leg.photo_url, alt: name }]
          : [{ url: "/og-default.png", width: 1200, height: 630 }],
      },
      twitter: {
        card: "summary_large_image",
        title: `${name} — Vigília`,
        description: desc,
        images: leg.photo_url ? [leg.photo_url] : ["/og-default.png"],
      },
    };
  } catch {
    return { title: "Deputado" };
  }
}

function RiskBadge({ score }: { score: number | null }) {
  if (score === null) return null;
  const cls =
    score > 0.6
      ? "bg-red-100 text-red-700"
      : score > 0.3
      ? "bg-yellow-100 text-yellow-700"
      : "bg-emerald-100 text-emerald-700";
  const label = score > 0.6 ? "alto risco" : score > 0.3 ? "risco médio" : "baixo risco";
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>{label}</span>;
}

function ScoreBar({
  value,
  min = -1,
  max = 1,
  onDark = false,
}: {
  value: number | null;
  min?: number;
  max?: number;
  onDark?: boolean;
}) {
  if (value === null)
    return (
      <span className={onDark ? "text-gray-400 text-sm" : "text-text-warm text-sm"}>
        —
      </span>
    );
  const pct = ((value - min) / (max - min)) * 100;
  const trackCls = onDark ? "bg-white/10" : "bg-concreto-shadow";
  const fillCls = onDark ? "bg-ipe" : "bg-cerrado";
  const numCls = onDark ? "text-ipe" : "text-brasilia";
  return (
    <div className="flex items-center gap-2">
      <div className={`flex-1 h-2 rounded-full overflow-hidden ${trackCls}`}>
        <div
          className={`h-full rounded-full ${fillCls}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-xs font-mono tabular-nums w-12 text-right ${numCls}`}>
        {value.toFixed(2)}
      </span>
    </div>
  );
}

export default async function DeputadoProfilePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let legislator, votesData, clustersData;
  try {
    [legislator, votesData, clustersData] = await Promise.all([
      getLegislator(id),
      getLegislatorVotes(id, 1),
      getClusters().catch(() => ({ clusters: [] })),
    ]);
  } catch {
    notFound();
  }

  const cluster =
    legislator.behavioral_cluster_id != null
      ? clustersData.clusters.find(
          (c) => c.id === legislator.behavioral_cluster_id,
        ) ?? null
      : null;

  const votes = votesData.items;
  const voteBreakdown = {
    sim: votes.filter((v) => v.vote_value === "sim").length,
    não: votes.filter((v) => v.vote_value === "não").length,
    abstencao: votes.filter((v) => v.vote_value === "abstencao").length,
    ausente: votes.filter((v) => v.vote_value === "ausente").length,
  };

  return (
    <main className="max-w-5xl mx-auto px-4 py-10">
      <Link
        href="/deputados"
        className="text-sm text-cerrado hover:text-ochre transition-colors mb-4 inline-block"
      >
        ← Todos os deputados
      </Link>

      {/* Header */}
      <div className="flex items-start gap-4 sm:gap-6 mb-8">
        {legislator.photo_url ? (
          <img
            src={legislator.photo_url}
            alt={legislator.display_name ?? legislator.name}
            className="w-20 h-20 sm:w-24 sm:h-24 rounded-lg object-cover ring-2 ring-concreto-shadow shrink-0"
          />
        ) : (
          <div className="w-20 h-20 sm:w-24 sm:h-24 rounded-lg bg-concreto-shadow flex items-center justify-center text-2xl sm:text-3xl text-text-warm font-bold shrink-0">
            {(legislator.display_name ?? legislator.name).charAt(0)}
          </div>
        )}
        <div className="min-w-0">
          <h1 className="font-display text-2xl sm:text-3xl font-bold text-brasilia break-words">
            {legislator.display_name ?? legislator.name}
          </h1>
          <p className="text-text-warm text-sm mt-1">
            {legislator.chamber === "camara" ? "Deputado Federal" : "Senador"} ·{" "}
            <span className="font-mono">{legislator.state_uf}</span>
            {legislator.party_acronym && (
              <>
                {" · "}
                <span className="font-semibold text-brasilia">
                  {legislator.party_acronym}
                </span>
              </>
            )}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        {/* Indicadores — dark Brasília card */}
        <div className="rounded-lg bg-brasilia text-white p-6 relative overflow-hidden">
          <div className="absolute inset-0 brasilia-grid pointer-events-none opacity-50" />
          <div className="relative">
            <h2 className="font-display text-sm font-bold text-ipe uppercase tracking-wider mb-5">
              Indicadores
            </h2>
            <div className="space-y-4">
              <div>
                <div className="flex justify-between text-xs text-gray-300 mb-1.5">
                  <span>Alinhamento CF/88</span>
                </div>
                <ScoreBar value={legislator.const_alignment_score} onDark />
              </div>
              <div>
                <div className="flex justify-between text-xs text-gray-300 mb-1.5">
                  <span>Disciplina partidária</span>
                </div>
                <ScoreBar
                  value={legislator.party_discipline_score}
                  min={0}
                  max={1}
                  onDark
                />
              </div>
              <div className="flex justify-between text-sm pt-1">
                <span className="text-gray-300">Taxa de ausência</span>
                <span className="text-white font-mono font-medium">
                  {legislator.absence_rate !== null
                    ? `${(legislator.absence_rate * 100).toFixed(1)}%`
                    : "—"}
                </span>
              </div>
              <div className="flex justify-between items-center text-sm">
                <span className="text-gray-300">Coalizão comportamental</span>
                {cluster?.label ? (
                  <span className="text-xs font-semibold px-3 py-1 rounded-full bg-ochre text-white">
                    {cluster.label}
                  </span>
                ) : (
                  <span className="text-gray-400">—</span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Vote breakdown card */}
        <div className="rounded-lg border border-concreto-shadow bg-concreto p-6">
          <h2 className="font-display text-sm font-bold text-brasilia uppercase tracking-wider mb-5">
            Votações recentes ({votesData.total} total)
          </h2>
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(voteBreakdown).map(([label, count]) => (
              <div
                key={label}
                className="text-center p-3 bg-concreto-shadow rounded-lg"
              >
                <div className="text-2xl font-display font-bold text-brasilia">
                  {count}
                </div>
                <div className="text-xs text-text-warm mt-0.5 capitalize">
                  {label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Voting history */}
      <section>
        <h2 className="font-display text-xl font-bold text-brasilia mb-4">
          Histórico de votações
        </h2>
        <div className="space-y-2">
          {votes.length === 0 ? (
            <p className="text-text-warm text-sm">Nenhuma votação registrada.</p>
          ) : (
            votes.map((v, i) => (
              <div
                key={i}
                className="flex items-start justify-between gap-4 p-4 rounded-lg border border-concreto-shadow bg-concreto hover:border-l-[3px] hover:border-l-ochre transition-all"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-brasilia line-clamp-2">{v.bill.title}</p>
                  <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                    <span className="text-xs text-text-warm font-mono">
                      {v.bill.type} {v.bill.number}/{v.bill.year}
                    </span>
                    <RiskBadge score={v.bill.const_risk_score} />
                    {v.donor_conflict_flag && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 font-medium">
                        conflito de doador
                      </span>
                    )}
                  </div>
                </div>
                <div className="shrink-0">
                  <span
                    className={`text-xs font-semibold px-3 py-1.5 rounded-md ${
                      v.vote_value === "sim"
                        ? "bg-cerrado text-white"
                        : v.vote_value === "não"
                        ? "bg-[#C0392B] text-white"
                        : "bg-text-warm/20 text-text-warm"
                    }`}
                  >
                    {v.vote_value}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </main>
  );
}

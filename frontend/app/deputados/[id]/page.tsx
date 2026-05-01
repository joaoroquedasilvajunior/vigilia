import type { Metadata } from "next";
import {
  getLegislator,
  getLegislatorVotes,
  getClusters,
  getLegislatorDonors,
  type LegislatorDonors,
  type DonorBucket,
  type DonorSector,
  type NamedDonor,
  type SectorVoteCorrelation,
} from "@/lib/api";
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

// ── Donor section helpers ────────────────────────────────────────────────────
const BUCKET_LABELS: Record<string, string> = {
  party_fund: "Fundo partidário (FEFC)",
  individual: "Pessoas físicas",
  company:    "Pessoas jurídicas",
  other:      "Outros",
};

const SECTOR_LABELS: Record<string, string> = {
  agronegocio:        "Agronegócio",
  financeiro:         "Setor financeiro",
  construtoras:       "Construtoras",
  religioso:          "Setor religioso",
  saude:              "Saúde",
  educacao:           "Educação",
  midia:              "Mídia",
  "energia-mineracao": "Energia / Mineração",
  armas:              "Armas",
  outros:             "Não classificado",
};

const THEME_LABELS_LOCAL: Record<string, string> = {
  agronegocio:        "agronegócio",
  "meio-ambiente":    "meio ambiente",
  indigenas:          "povos indígenas",
  tributacao:         "tributação",
  "reforma-politica": "reforma política",
  religiao:           "religião",
  "direitos-lgbtqia": "direitos LGBTQIA+",
  armas:              "armas",
  "seguranca-publica": "segurança pública",
  saude:              "saúde",
  educacao:           "educação",
  midia:              "mídia",
};

function fmtBRL(n: number): string {
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
}

function FundingBar({
  bucket,
  totalReceived,
}: {
  bucket: DonorBucket;
  totalReceived: number;
}) {
  const pct = totalReceived > 0 ? (bucket.total_brl / totalReceived) * 100 : 0;
  // Color by funding source
  const fillCls =
    bucket.bucket === "party_fund"
      ? "bg-text-warm"
      : bucket.bucket === "individual"
      ? "bg-cerrado"
      : bucket.bucket === "company"
      ? "bg-ochre"
      : "bg-concreto-shadow";
  return (
    <div>
      <div className="flex justify-between items-baseline text-sm mb-1">
        <span className="text-brasilia">
          {BUCKET_LABELS[bucket.bucket] ?? bucket.bucket}
          <span className="text-xs text-text-warm ml-2">
            ({bucket.donor_count})
          </span>
        </span>
        <span className="font-mono text-ochre text-sm">{fmtBRL(bucket.total_brl)}</span>
      </div>
      <div className="h-2 bg-concreto-shadow rounded-full overflow-hidden">
        <div
          className={`h-full ${fillCls} rounded-full`}
          style={{ width: `${pct.toFixed(1)}%` }}
        />
      </div>
    </div>
  );
}

function SectorRow({
  s,
  totalReceived,
}: {
  s: DonorSector;
  totalReceived: number;
}) {
  const pct = totalReceived > 0 ? (s.total_brl / totalReceived) * 100 : 0;
  const label = s.sector ? (SECTOR_LABELS[s.sector] ?? s.sector) : "Não classificado";
  return (
    <div>
      <div className="flex justify-between items-baseline text-sm mb-1">
        <span className="text-brasilia">
          {label}
          <span className="text-xs text-text-warm ml-2">({s.donor_count})</span>
        </span>
        <span className="font-mono text-ochre text-sm">{fmtBRL(s.total_brl)}</span>
      </div>
      <div className="h-1.5 bg-concreto-shadow rounded-full overflow-hidden">
        <div
          className="h-full bg-cerrado rounded-full"
          style={{ width: `${pct.toFixed(1)}%` }}
        />
      </div>
    </div>
  );
}

function NamedDonorRow({ d }: { d: NamedDonor }) {
  const sectorLabel = d.sector
    ? SECTOR_LABELS[d.sector] ?? d.sector
    : "—";
  return (
    <li className="flex items-baseline justify-between gap-3 py-2 border-b border-concreto-shadow last:border-0">
      <div className="min-w-0">
        <p className="text-sm text-brasilia truncate">{d.name}</p>
        <p className="text-xs text-text-warm">
          {d.entity_type === "pessoa_juridica" ? "PJ" : "PF"} · {sectorLabel}
        </p>
      </div>
      <span className="font-mono text-sm text-ochre shrink-0">
        {fmtBRL(d.total_brl)}
      </span>
    </li>
  );
}

function CorrelationCallout({ c }: { c: SectorVoteCorrelation }) {
  // Render a plain-language sentence about how this deputy voted on
  // bills thematically aligned with a sector that funded their campaign.
  const sectorName = SECTOR_LABELS[c.sector] ?? c.sector;
  const themeText = c.themes
    .map((t) => THEME_LABELS_LOCAL[t] ?? t)
    .join(" / ");
  if (c.votes.total === 0) {
    // We have donor money but no aligned bills to correlate against
    return (
      <p className="text-sm text-text-warm">
        Recebeu <span className="font-mono text-ochre">{fmtBRL(c.amount_brl)}</span>{" "}
        do setor <strong className="text-brasilia">{sectorName}</strong>. Nenhum
        projeto sobre {themeText} foi votado no recorte atual.
      </p>
    );
  }
  return (
    <p className="text-sm text-text-warm leading-relaxed">
      Recebeu <span className="font-mono text-ochre">{fmtBRL(c.amount_brl)}</span>{" "}
      do setor <strong className="text-brasilia">{sectorName}</strong> e votou{" "}
      <span className="font-mono text-cerrado font-semibold">
        SIM em {c.votes.sim}
      </span>{" "}
      e{" "}
      <span className="font-mono text-[#C0392B] font-semibold">
        NÃO em {c.votes.nao}
      </span>{" "}
      dos <span className="font-mono">{c.votes.total}</span> projetos sobre{" "}
      {themeText}.
    </p>
  );
}

function DonorSection({ data }: { data: LegislatorDonors | null }) {
  if (!data || (data.funding_breakdown.length === 0 && data.top_donors.length === 0)) {
    return (
      <section className="mb-8">
        <h2 className="font-display text-xl font-bold text-brasilia mb-3">
          Financiamento eleitoral
          <span className="text-sm font-sans font-normal text-text-warm ml-2">
            (TSE 2022)
          </span>
        </h2>
        <p className="text-sm text-text-warm italic">
          Sem vínculos de financiamento registrados no TSE 2022.
        </p>
      </section>
    );
  }

  // Filter out "Não classificado" rows when they're the only thing — that
  // means sector data is fully absent for this deputy and showing the row
  // adds noise rather than information.
  const meaningfulSectors = data.sector_breakdown.filter(
    (s) => s.sector && s.sector !== "outros",
  );
  // Filter correlations that yielded no aligned-theme votes when they
  // ALSO have <R$ 5k of non-PF money (the backend already filters this,
  // but defend in depth).
  const correlations = data.correlations;

  return (
    <section className="mb-8">
      <h2 className="font-display text-xl font-bold text-brasilia mb-1">
        Financiamento eleitoral
        <span className="text-sm font-sans font-normal text-text-warm ml-2">
          (TSE 2022)
        </span>
      </h2>
      <p className="text-sm text-text-warm mb-5">
        Total recebido:{" "}
        <span className="font-mono text-ochre font-semibold">
          {fmtBRL(data.total_received_brl)}
        </span>
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Funding source breakdown — always populated */}
        <div className="rounded-lg border border-concreto-shadow bg-concreto p-5">
          <h3 className="font-display text-sm font-bold text-brasilia uppercase tracking-wider mb-4">
            Origem dos recursos
          </h3>
          <div className="space-y-3">
            {data.funding_breakdown.map((b) => (
              <FundingBar
                key={b.bucket}
                bucket={b}
                totalReceived={data.total_received_brl}
              />
            ))}
          </div>
        </div>

        {/* Top named donors */}
        <div className="rounded-lg border border-concreto-shadow bg-concreto p-5">
          <h3 className="font-display text-sm font-bold text-brasilia uppercase tracking-wider mb-3">
            Maiores doadores nominados
          </h3>
          {data.top_donors.length === 0 ? (
            <p className="text-sm text-text-warm italic">
              Sem doadores nominados além de transferências de fundo partidário.
            </p>
          ) : (
            <ul>
              {data.top_donors.map((d, i) => (
                <NamedDonorRow key={`${d.name}-${i}`} d={d} />
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Sector breakdown — only render when there's signal beyond "outros" */}
      {meaningfulSectors.length > 0 && (
        <div className="rounded-lg border border-concreto-shadow bg-concreto p-5 mb-6">
          <h3 className="font-display text-sm font-bold text-brasilia uppercase tracking-wider mb-4">
            Por setor econômico
          </h3>
          <div className="space-y-3">
            {meaningfulSectors.map((s) => (
              <SectorRow
                key={s.sector ?? "none"}
                s={s}
                totalReceived={data.total_received_brl}
              />
            ))}
          </div>
        </div>
      )}

      {/* Correlation callouts — only render when there's signal */}
      {correlations.length > 0 && (
        <div className="rounded-lg border-l-[3px] border-l-ochre border border-concreto-shadow bg-concreto p-5">
          <h3 className="font-display text-sm font-bold text-brasilia uppercase tracking-wider mb-3">
            Doação ↔ voto temático
          </h3>
          <div className="space-y-3">
            {correlations.map((c) => (
              <CorrelationCallout key={c.sector} c={c} />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

export default async function DeputadoProfilePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let legislator, votesData, clustersData, donorsData: LegislatorDonors | null;
  try {
    [legislator, votesData, clustersData, donorsData] = await Promise.all([
      getLegislator(id),
      getLegislatorVotes(id, 1),
      getClusters().catch(() => ({ clusters: [] })),
      getLegislatorDonors(id).catch(() => null),
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

      {/* Donor exposure */}
      <DonorSection data={donorsData} />

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

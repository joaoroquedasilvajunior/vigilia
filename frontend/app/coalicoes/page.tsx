import type { Metadata } from "next";
import Link from "next/link";
import { getClusters, type BehavioralCluster, type ClusterMemberPreview } from "@/lib/api";

// Render per-request — listing depends on live cluster data, not prerenderable
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Coalizões Comportamentais",
  description:
    "Mapa das coalizões reais do Congresso brasileiro, baseado em " +
    "votações — não em filiação partidária.",
  openGraph: {
    type: "website",
    title: "Coalizões Comportamentais — Vigília",
    description:
      "Mapa das coalizões reais do Congresso brasileiro, baseado em " +
      "votações — não em filiação partidária.",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
};

const THEME_LABELS: Record<string, string> = {
  trabalho: "Trabalho",
  "meio-ambiente": "Meio Ambiente",
  saude: "Saúde",
  educacao: "Educação",
  "seguranca-publica": "Segurança Pública",
  agronegocio: "Agronegócio",
  tributacao: "Tributação",
  "direitos-lgbtqia": "Direitos LGBTQIA+",
  armas: "Armas",
  religiao: "Religião",
  indigenas: "Indígenas",
  midia: "Mídia",
  "reforma-politica": "Reforma Política",
};

function ThemeChip({ slug }: { slug: string }) {
  return (
    <span className="text-xs px-2.5 py-1 rounded-full bg-cerrado text-white font-medium">
      {THEME_LABELS[slug] ?? slug}
    </span>
  );
}

// Match cluster label to its modernist accent palette.
// Falls back to ochre for unrecognized labels.
function clusterTheme(label: string | null): {
  accentLeft: string;
  bg: string;
  text: string;
  meta: string;
} {
  const l = (label ?? "").toLowerCase();
  if (l.includes("bolsonarista")) {
    return {
      accentLeft: "before:bg-brasilia",
      bg: "bg-brasilia",
      text: "text-white",
      meta: "text-gray-300",
    };
  }
  if (l.includes("centrão") || l.includes("centrao")) {
    return {
      accentLeft: "before:bg-ochre",
      bg: "bg-concreto",
      text: "text-brasilia",
      meta: "text-text-warm",
    };
  }
  // Governista / default
  return {
    accentLeft: "before:bg-cerrado",
    bg: "bg-concreto",
    text: "text-brasilia",
    meta: "text-text-warm",
  };
}

function MemberThumb({
  m,
  onDark = false,
}: {
  m: ClusterMemberPreview;
  onDark?: boolean;
}) {
  const ringIdle = onDark ? "ring-white/10" : "ring-concreto-shadow";
  const nameCls = onDark
    ? "text-white group-hover:text-ipe"
    : "text-brasilia group-hover:text-cerrado";
  const metaCls = onDark ? "text-gray-400" : "text-text-warm";
  return (
    <Link
      href={`/deputados/${m.id}`}
      className="flex flex-col items-center gap-1.5 group"
    >
      {m.photo_url ? (
        <img
          src={m.photo_url}
          alt={m.name}
          className={`w-14 h-14 rounded-full object-cover ring-2 ${ringIdle} group-hover:ring-ipe transition-all`}
        />
      ) : (
        <div
          className={`w-14 h-14 rounded-full bg-gray-300 flex items-center justify-center text-gray-600 font-bold ring-2 ${ringIdle} group-hover:ring-ipe transition-all`}
        >
          {m.name.charAt(0)}
        </div>
      )}
      <span
        className={`text-xs font-medium text-center line-clamp-1 transition-colors max-w-[8rem] ${nameCls}`}
      >
        {m.name}
      </span>
      <span className={`text-[10px] ${metaCls}`}>
        {m.party_acronym ?? "—"} · {m.state_uf ?? "—"}
      </span>
    </Link>
  );
}

function ClusterCard({ c }: { c: BehavioralCluster }) {
  const topParties = Object.entries(c.party_distribution)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  const cohesionPct = c.cohesion_score
    ? `${Math.round(c.cohesion_score * 100)}%`
    : "—";

  const t = clusterTheme(c.label);
  const onDark = t.bg === "bg-brasilia";
  const partyNumCls = onDark ? "text-gray-400" : "text-text-warm";
  const partyKeyCls = onDark ? "text-white" : "text-brasilia";
  const dividerCls = onDark ? "text-gray-600" : "text-gray-300";
  const borderTopCls = onDark ? "border-white/10" : "border-concreto-shadow";
  const linkCls = onDark
    ? "text-ipe hover:brightness-110"
    : "text-cerrado hover:text-ochre";

  return (
    <section
      className={`relative ${t.bg} ${t.text} rounded-lg border border-concreto-shadow p-6 pl-7 overflow-hidden before:absolute before:left-0 before:top-0 before:bottom-0 before:w-1 ${t.accentLeft}`}
    >
      {/* Header */}
      <div className="flex items-baseline justify-between gap-4 mb-1 flex-wrap">
        <h2 className={`font-display text-2xl font-bold ${t.text}`}>
          {c.label ?? "Cluster sem rótulo"}
        </h2>
        <p className={`text-sm ${t.meta} font-mono`}>
          {c.member_count ?? 0} deputados · cohesão {cohesionPct}
        </p>
      </div>

      {/* Themes */}
      {c.dominant_themes && c.dominant_themes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3 mb-4">
          {c.dominant_themes.map((slug) => (
            <ThemeChip key={slug} slug={slug} />
          ))}
        </div>
      )}

      {/* Party distribution */}
      {topParties.length > 0 && (
        <p className={`text-sm mb-5 ${t.meta}`}>
          {topParties.map(([party, n], i) => (
            <span key={party}>
              <span className={`font-semibold ${partyKeyCls}`}>{party}</span>{" "}
              <span className={`font-mono ${partyNumCls}`}>{n}</span>
              {i < topParties.length - 1 && (
                <span className={`mx-2 ${dividerCls}`}>·</span>
              )}
            </span>
          ))}
        </p>
      )}

      {/* Top members */}
      {c.top_members.length > 0 && (
        <div className="mt-5">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {c.top_members.slice(0, 6).map((m) => (
              <MemberThumb key={m.id} m={m} onDark={onDark} />
            ))}
          </div>
        </div>
      )}

      {/* See all */}
      <div className={`mt-6 pt-4 border-t ${borderTopCls}`}>
        <Link
          href={`/coalicoes/${c.id}`}
          className={`inline-flex items-center gap-1 text-sm font-medium transition-colors ${linkCls}`}
        >
          Ver todos os {c.member_count ?? 0} membros →
        </Link>
      </div>
    </section>
  );
}

export default async function CoalicoesPage() {
  const data = await getClusters();
  const clusters = data.clusters ?? [];

  return (
    <main className="max-w-5xl mx-auto px-4 py-10">
      <h1 className="font-display text-3xl font-bold text-brasilia mb-2">
        Coalizões
      </h1>
      <p className="text-text-warm text-sm mb-8 max-w-2xl">
        Grupos de deputados identificados pelo comportamento real de voto
        — não pelo partido oficial. Atualizado a cada nova análise.
      </p>

      {clusters.length === 0 ? (
        <div className="rounded-lg border border-concreto-shadow p-8 text-center text-text-warm">
          Nenhuma coalizão calculada ainda.
        </div>
      ) : (
        <div className="space-y-5">
          {clusters.map((c) => (
            <ClusterCard key={c.id} c={c} />
          ))}
        </div>
      )}
    </main>
  );
}

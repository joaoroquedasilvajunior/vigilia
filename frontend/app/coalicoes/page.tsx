import Link from "next/link";
import { getClusters, type BehavioralCluster, type ClusterMemberPreview } from "@/lib/api";

// Render per-request — listing depends on live cluster data, not prerenderable
export const dynamic = "force-dynamic";

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
    <span className="text-xs px-2.5 py-1 rounded-full bg-purple-50 text-purple-700 font-medium border border-purple-100">
      {THEME_LABELS[slug] ?? slug}
    </span>
  );
}

function MemberThumb({ m }: { m: ClusterMemberPreview }) {
  return (
    <Link
      href={`/deputados/${m.id}`}
      className="flex flex-col items-center gap-1.5 group"
    >
      {m.photo_url ? (
        <img
          src={m.photo_url}
          alt={m.name}
          className="w-14 h-14 rounded-full object-cover ring-2 ring-gray-100 group-hover:ring-blue-300 transition-all"
        />
      ) : (
        <div className="w-14 h-14 rounded-full bg-gray-200 flex items-center justify-center text-gray-500 font-bold ring-2 ring-gray-100 group-hover:ring-blue-300 transition-all">
          {m.name.charAt(0)}
        </div>
      )}
      <span className="text-xs text-gray-900 font-medium text-center line-clamp-1 group-hover:text-blue-600 transition-colors max-w-[8rem]">
        {m.name}
      </span>
      <span className="text-[10px] text-gray-500">
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

  return (
    <section className="rounded-2xl border border-gray-200 p-6 bg-white">
      {/* Header */}
      <div className="flex items-baseline justify-between gap-4 mb-1 flex-wrap">
        <h2 className="text-xl font-bold text-gray-900">
          {c.label ?? "Cluster sem rótulo"}
        </h2>
        <p className="text-sm text-gray-500">
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
        <p className="text-sm text-gray-600 mb-5">
          {topParties.map(([party, n], i) => (
            <span key={party}>
              <span className="font-semibold text-gray-900">{party}</span>{" "}
              <span className="text-gray-500">{n}</span>
              {i < topParties.length - 1 && (
                <span className="mx-2 text-gray-300">·</span>
              )}
            </span>
          ))}
        </p>
      )}

      {/* Top members */}
      {c.top_members.length > 0 && (
        <div className="mt-5">
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
            {c.top_members.slice(0, 6).map((m) => (
              <MemberThumb key={m.id} m={m} />
            ))}
          </div>
        </div>
      )}

      {/* See all */}
      <div className="mt-6 pt-4 border-t border-gray-100">
        <Link
          href={`/coalicoes/${c.id}`}
          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 font-medium transition-colors"
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
    <main className="max-w-5xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Coalizões</h1>
      <p className="text-gray-500 text-sm mb-6">
        Grupos de deputados identificados pelo comportamento real de voto
        — não pelo partido oficial. Atualizado a cada nova análise.
      </p>

      {clusters.length === 0 ? (
        <div className="rounded-2xl border border-gray-200 p-8 text-center text-gray-500">
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

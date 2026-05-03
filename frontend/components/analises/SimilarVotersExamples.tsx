import Link from "next/link";
import Image from "next/image";
import type { SimilarVoter } from "@/lib/api";

export interface ExampleDeputy {
  id: string;
  name: string;
  party: string;
  state: string;
}
export interface ExampleResult {
  deputy: ExampleDeputy;
  matches: SimilarVoter[];
}

// Same spectrum buckets used by the on-profile widget so the ⚡ flag
// fires on the same conditions in both places.
const LEFT_PARTIES  = new Set(["PT", "PSOL", "PCDOB", "PCdoB", "PV", "REDE"]);
const RIGHT_PARTIES = new Set(["PL", "NOVO", "PSC", "REPUBLICANOS", "PRTB"]);

function partyAxis(p: string | null): "L" | "R" | "C" {
  if (!p) return "C";
  if (LEFT_PARTIES.has(p)) return "L";
  if (RIGHT_PARTIES.has(p)) return "R";
  return "C";
}
function isOppositeSpectrum(a: string | null, b: string | null): boolean {
  const x = partyAxis(a), y = partyAxis(b);
  return (x === "L" && y === "R") || (x === "R" && y === "L");
}

// "Different cluster" callout — fires for any cross-cluster pair where
// similarity is high enough to be interesting. We use cluster differences
// as the surfacing signal in addition to the stricter spectrum check, so
// users see at least one ⚡ on the page even when no example crosses the
// hard L↔R divide. The page-level callout below picks the *strongest* such
// pair across all three columns.
function pickHeadlinePair(examples: ExampleResult[]): {
  ex: ExampleResult;
  match: SimilarVoter;
} | null {
  let best: { ex: ExampleResult; match: SimilarVoter; score: number } | null = null;
  for (const ex of examples) {
    for (const m of ex.matches) {
      // Prefer hard-spectrum crossings, then high-pct cross-party in general.
      const sim = m.similarity_pct ?? 0;
      const spectrumBonus = isOppositeSpectrum(ex.deputy.party, m.party) ? 100 : 0;
      const score = spectrumBonus + sim;
      if (sim >= 75 && (!best || score > best.score)) {
        best = { ex, match: m, score };
      }
    }
  }
  return best ? { ex: best.ex, match: best.match } : null;
}

function clusterChipClass(label: string | null): string {
  if (!label) return "bg-gray-300 text-brasilia";
  const l = label.toLowerCase();
  if (/coaliz[aã]o\s+govern/.test(l)) return "bg-cerrado text-white";
  if (/centr[aã]o/.test(l))           return "bg-ochre text-white";
  if (/bolsonar/.test(l))             return "bg-brasilia text-white";
  return "bg-gray-300 text-brasilia";
}

export default function SimilarVotersExamples({
  examples,
}: {
  examples: ExampleResult[];
}) {
  // Drop any example that came back empty so the grid doesn't show stub cards
  const valid = examples.filter((e) => e.matches.length > 0);
  if (valid.length === 0) return null;

  const headline = pickHeadlinePair(valid);

  return (
    <div className="space-y-5">
      {headline && (
        <div className="rounded-lg border-l-[4px] border-l-ipe bg-ipe/10 px-4 py-3 text-sm text-brasilia leading-relaxed">
          <span className="font-display font-bold mr-1.5">⚡</span>
          <Link
            href={`/deputados/${headline.ex.deputy.id}`}
            className="font-semibold hover:text-cerrado transition-colors"
          >
            {headline.ex.deputy.name}
          </Link>{" "}
          ({headline.ex.deputy.party}) e{" "}
          <Link
            href={`/deputados/${headline.match.id}`}
            className="font-semibold hover:text-cerrado transition-colors"
          >
            {headline.match.name}
          </Link>{" "}
          ({headline.match.party}) votaram igual em{" "}
          <span className="font-mono font-semibold">
            {Math.round(headline.match.similarity_pct ?? 0)}%
          </span>{" "}
          das votações analisadas — apesar de partidos diferentes.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {valid.map((ex) => (
          <ExampleCard key={ex.deputy.id} example={ex} />
        ))}
      </div>

      <div className="text-center pt-1">
        <Link
          href="/deputados"
          className="inline-flex items-center gap-2 text-sm font-semibold text-cerrado hover:text-ochre transition-colors"
        >
          Buscar qualquer deputado →
        </Link>
      </div>
    </div>
  );
}

function ExampleCard({ example }: { example: ExampleResult }) {
  const { deputy, matches } = example;
  const top3 = matches.slice(0, 3);

  return (
    <article className="bg-white rounded-lg border border-concreto-shadow shadow-sm overflow-hidden flex flex-col">
      {/* Header — the deputy this column is "about" */}
      <header className="bg-brasilia text-white px-4 py-3">
        <p className="font-display font-bold text-base leading-tight">
          {deputy.name}
        </p>
        <p className="text-[11px] text-gray-300 mt-0.5 font-mono">
          {deputy.party} · {deputy.state}
        </p>
      </header>

      <div className="p-4 flex-1 flex flex-col">
        <p className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest mb-3">
          Vota mais com
        </p>

        <ul className="space-y-3 flex-1">
          {top3.map((m) => {
            const pct = Math.round(m.similarity_pct ?? 0);
            const spectrum = isOppositeSpectrum(deputy.party, m.party);
            return (
              <li key={m.id}>
                <Link
                  href={`/deputados/${m.id}`}
                  className="flex items-center gap-3 group"
                >
                  {/* Photo */}
                  {m.photo_url ? (
                    <Image
                      src={m.photo_url}
                      alt=""
                      width={40}
                      height={40}
                      className="rounded-full object-cover bg-concreto-shadow shrink-0"
                      unoptimized
                    />
                  ) : (
                    <div className="w-10 h-10 rounded-full bg-concreto-shadow flex items-center justify-center text-text-warm font-display text-sm shrink-0">
                      {(m.name[0] ?? "?").toUpperCase()}
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-brasilia leading-tight group-hover:text-cerrado transition-colors line-clamp-1">
                      {m.name}
                      {spectrum && (
                        <span
                          className="ml-1 text-ipe"
                          title="Cruzamento de espectro político"
                        >
                          ⚡
                        </span>
                      )}
                    </p>
                    <p className="text-[11px] text-text-warm font-mono mt-0.5">
                      {(m.party ?? "—")} · {(m.state_uf ?? "—")}
                      {m.cluster_label && (
                        <span
                          className={`ml-1.5 inline-block text-[9px] px-1.5 py-0.5 rounded-full ${clusterChipClass(m.cluster_label)}`}
                        >
                          {m.cluster_label}
                        </span>
                      )}
                    </p>
                    <div className="mt-1 flex items-center gap-2">
                      <div className="flex-1 h-1 bg-concreto-shadow rounded-full overflow-hidden">
                        <div
                          className="h-full bg-cerrado"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="font-mono text-xs font-semibold text-brasilia w-9 text-right">
                        {pct}%
                      </span>
                    </div>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>

        <Link
          href={`/deputados/${deputy.id}`}
          className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-cerrado hover:text-ochre transition-colors self-start"
        >
          Ver perfil de {deputy.name.split(" ")[0]} →
        </Link>
      </div>
    </article>
  );
}

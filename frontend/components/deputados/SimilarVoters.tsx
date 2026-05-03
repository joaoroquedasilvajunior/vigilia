import Link from "next/link";
import Image from "next/image";
import type { SimilarVoter } from "@/lib/api";

// Spectrum buckets for the "⚡ surprise crossing" callout. These reflect
// 2023+ Câmara reality: PT/PSOL/PCdoB on the left axis, PL/NOVO/PSC on the
// right. Bucketing by acronym is fragile but the alternative (manually
// curated MP→ideology mapping) is just as fragile and harder to maintain.
const LEFT_PARTIES  = new Set(["PT", "PSOL", "PCDOB", "PCdoB", "PV", "REDE"]);
const RIGHT_PARTIES = new Set(["PL", "NOVO", "PSC", "REPUBLICANOS", "PRTB"]);

function partyAxis(p: string | null): "L" | "R" | "C" {
  if (!p) return "C";
  if (LEFT_PARTIES.has(p)) return "L";
  if (RIGHT_PARTIES.has(p)) return "R";
  return "C";
}

function isOppositeSpectrum(targetParty: string | null, otherParty: string | null): boolean {
  const a = partyAxis(targetParty);
  const b = partyAxis(otherParty);
  return (a === "L" && b === "R") || (a === "R" && b === "L");
}

// Reuse the cluster palette from the scatter so the "different cluster"
// badge color reads consistently across the site.
function clusterChipClass(label: string | null): string {
  if (!label) return "bg-gray-300 text-brasilia";
  const l = label.toLowerCase();
  if (/coaliz[aã]o\s+govern/.test(l)) return "bg-cerrado text-white";
  if (/centr[aã]o/.test(l)) return "bg-ochre text-white";
  if (/bolsonar/.test(l)) return "bg-brasilia text-white";
  return "bg-gray-300 text-brasilia";
}

export default function SimilarVoters({
  voters,
  targetName,
  targetParty,
  targetClusterId,
}: {
  voters: SimilarVoter[];
  targetName: string;
  targetParty: string | null;
  targetClusterId: string | null;
}) {
  // Hide the section entirely if the data is too thin to be a finding
  // (per spec: at least 5).
  if (voters.length < 5) return null;

  const top = voters[0];
  const showCallout =
    top &&
    (top.similarity_pct ?? 0) > 75 &&
    isOppositeSpectrum(targetParty, top.party);

  return (
    <section>
      <div className="mb-4 max-w-3xl">
        <h2 className="font-display text-xl font-bold text-brasilia">
          Quem vota igual
        </h2>
        <p className="text-sm text-text-warm mt-1.5 leading-relaxed">
          Deputados de outros partidos com padrão de voto mais parecido com{" "}
          <strong className="text-brasilia">{targetName}</strong>.
        </p>
      </div>

      {showCallout && (
        <div className="mb-5 rounded-lg border-l-[4px] border-l-ipe bg-ipe/10 px-4 py-3 text-sm text-brasilia leading-relaxed">
          <span className="font-display font-bold mr-1.5">⚡ Cruzamento de espectro:</span>
          Apesar de partidos diferentes,{" "}
          <strong>{targetName}</strong> e{" "}
          <Link
            href={`/deputados/${top.id}`}
            className="text-cerrado hover:text-ochre underline underline-offset-2"
          >
            {top.name}
          </Link>{" "}
          ({top.party}/{top.state_uf}) votaram da mesma forma em{" "}
          <span className="font-mono font-semibold">{Math.round(top.similarity_pct ?? 0)}%</span>{" "}
          das <span className="font-mono">{top.shared_votes}</span> votações em comum.
        </div>
      )}

      {/* Horizontal scrolling list of cards — works on mobile and desktop */}
      <div className="overflow-x-auto -mx-4 sm:mx-0">
        <ul className="flex gap-3 px-4 sm:px-0 pb-2 snap-x snap-mandatory">
          {voters.map((v) => {
            const pct = Math.round(v.similarity_pct ?? 0);
            const differentCluster =
              v.cluster_id != null && targetClusterId != null && v.cluster_id !== targetClusterId;
            return (
              <li
                key={v.id}
                className="snap-start shrink-0"
                style={{ width: 168 }}
              >
                <Link
                  href={`/deputados/${v.id}`}
                  className="group block bg-white rounded-lg border border-concreto-shadow p-3 hover:border-l-[3px] hover:border-l-cerrado transition-all h-full"
                >
                  {/* Photo */}
                  <div className="flex justify-center mb-2">
                    {v.photo_url ? (
                      <Image
                        src={v.photo_url}
                        alt=""
                        width={48}
                        height={48}
                        className="rounded-full object-cover bg-concreto-shadow"
                        unoptimized
                      />
                    ) : (
                      <div className="w-12 h-12 rounded-full bg-concreto-shadow flex items-center justify-center text-text-warm font-display text-sm">
                        {(v.name[0] ?? "?").toUpperCase()}
                      </div>
                    )}
                  </div>

                  {/* Name + party · UF */}
                  <p className="text-sm font-display font-bold text-brasilia leading-tight line-clamp-2 text-center">
                    {v.name}
                  </p>
                  <p className="text-[11px] text-text-warm mt-0.5 text-center font-mono">
                    {(v.party ?? "—")} · {(v.state_uf ?? "—")}
                  </p>

                  {/* Optional surprise badge */}
                  {differentCluster && v.cluster_label && (
                    <p className="mt-1.5 text-center">
                      <span
                        className={`inline-block text-[9px] px-1.5 py-0.5 rounded-full ${clusterChipClass(v.cluster_label)}`}
                        title="Cluster comportamental diferente do deputado em foco"
                      >
                        {v.cluster_label}
                      </span>
                    </p>
                  )}

                  {/* Similarity bar */}
                  <div className="mt-3">
                    <div className="h-1.5 bg-concreto-shadow rounded-full overflow-hidden">
                      <div
                        className="h-full bg-cerrado"
                        style={{ width: `${pct}%` }}
                        aria-label={`${pct}% de similaridade`}
                      />
                    </div>
                    <p className="mt-1 text-center font-mono text-sm font-semibold text-brasilia">
                      {pct}%
                    </p>
                  </div>

                  <p className="mt-1 text-center text-[10px] text-text-warm leading-tight">
                    <span className="font-mono">{v.shared_votes}</span> votos em comum
                  </p>
                </Link>
              </li>
            );
          })}
        </ul>
      </div>

      <p className="mt-3 text-[11px] text-text-warm/80 max-w-2xl">
        Similaridade calculada sobre todas as votações em que ambos os deputados
        participaram (mínimo de 30 em comum). Apenas deputados de outros partidos
        — alinhamento dentro do mesmo partido é o esperado.
      </p>
    </section>
  );
}

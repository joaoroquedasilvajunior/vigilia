import type { PartyCohesionRow } from "@/lib/api";

// Cluster colors for the segmented bar — same palette as everywhere else.
function clusterColor(label: string): string {
  const l = label.toLowerCase();
  if (/coaliz[aã]o\s+govern/.test(l)) return "#1B4332";
  if (/centr[aã]o/.test(l))           return "#C17D3C";
  if (/bolsonar/.test(l))             return "#1A1F2E";
  return "#94a3b8";
}

export default function PartyCohesion({ rows }: { rows: PartyCohesionRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-concreto-shadow p-8 text-center">
        <p className="text-text-warm">Sem dados de coesão partidária.</p>
      </div>
    );
  }

  // Centrão signal: parties whose delegation spans 3 different behavioral clusters.
  const fragmented = rows.filter((r) => r.clusters_present.length >= 3);

  return (
    <div className="space-y-5">
      <div className="bg-white rounded-lg border border-concreto-shadow shadow-sm overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-concreto-shadow bg-concreto-shadow/30">
              <th className="text-left px-3 py-2 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest" style={{ width: 40 }}>
                #
              </th>
              <th className="text-left px-3 py-2 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
                Partido
              </th>
              <th className="text-left px-3 py-2 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
                Coesão
              </th>
              <th className="text-right px-3 py-2 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest hidden sm:table-cell">
                Membros
              </th>
              <th className="text-left px-3 py-2 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest hidden md:table-cell">
                Coalizões
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const score = r.cohesion_score ?? 0;
              const pct = Math.round(score * 100);
              const clusters = r.clusters_present;
              const fragmented3 = clusters.length >= 3;
              const split = clusters.length === 2;
              return (
                <tr
                  key={r.id}
                  className="border-b border-concreto-shadow last:border-b-0 hover:bg-concreto/40 transition-colors"
                >
                  <td className="px-3 py-2 text-text-warm font-mono text-xs align-middle">
                    {i + 1}
                  </td>
                  <td className="px-3 py-2 align-middle">
                    <p className="font-display font-bold text-brasilia text-sm">
                      {r.acronym}
                    </p>
                  </td>
                  <td className="px-3 py-2 align-middle" style={{ minWidth: 220 }}>
                    {/* Segmented bar — one segment per cluster present, weighted equally.
                        Single-cluster: solid. Two: split. Three+: fragmented (Centrão signal). */}
                    <div className="flex items-center gap-2">
                      <div
                        className="h-2 rounded-full overflow-hidden flex flex-1"
                        style={{ minWidth: 80 }}
                      >
                        {(clusters.length > 0 ? clusters : ["—"]).map((c, ci) => (
                          <div
                            key={`${c}-${ci}`}
                            className="h-full transition-all"
                            style={{
                              flexBasis: `${(score / clusters.length || 1) * 100}%`,
                              backgroundColor: c === "—" ? "#94a3b8" : clusterColor(c),
                              opacity: 0.95,
                            }}
                            title={c}
                          />
                        ))}
                        {/* Fill the unused portion with concreto-shadow to show the score visually */}
                        <div
                          className="h-full bg-concreto-shadow"
                          style={{ flexBasis: `${(1 - score) * 100}%` }}
                        />
                      </div>
                      <span className="font-mono text-xs font-semibold text-brasilia w-9 text-right">
                        {pct}%
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-text-warm align-middle hidden sm:table-cell">
                    {r.member_count}
                  </td>
                  <td className="px-3 py-2 text-xs text-text-warm align-middle hidden md:table-cell">
                    <span
                      className={`inline-flex items-center gap-1 ${
                        fragmented3
                          ? "text-ochre font-semibold"
                          : split
                          ? "text-brasilia"
                          : ""
                      }`}
                    >
                      {clusters.length === 0
                        ? "—"
                        : `${clusters.length} cluster${clusters.length === 1 ? "" : "s"}`}
                      {fragmented3 && (
                        <span className="text-[9px] uppercase tracking-wider">
                          • fragmentado
                        </span>
                      )}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {fragmented.length > 0 && (
        <article className="bg-white rounded-lg border border-concreto-shadow border-l-[4px] border-l-ochre p-4 text-sm text-brasilia leading-relaxed">
          <p>
            Partidos presentes em <strong>3 coalizões diferentes</strong>:{" "}
            <span className="font-mono font-semibold">
              {fragmented.map((p) => p.acronym).join(", ")}
            </span>
            . Mesma legenda, comportamentos opostos — o sinal clássico do{" "}
            <strong>Centrão</strong>: o partido formal pesa menos do que a
            negociação caso a caso com o governo de plantão.
          </p>
        </article>
      )}
    </div>
  );
}

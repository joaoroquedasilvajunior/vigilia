"use client";

import Link from "next/link";
import Image from "next/image";
import { useMemo, useState } from "react";
import type { StateProfile } from "@/lib/api";

// ── UF tile-grid layout ────────────────────────────────────────────────────
// (col, row) coordinates for each of Brazil's 27 federative units, arranged
// in a Brazilian-press-style tile map. Norte top-left, Nordeste top-right,
// Centro-Oeste center, Sudeste lower-center, Sul bottom-left. Equal-weight
// tiles avoid the "Roraima is invisible because it's geographically tiny"
// problem of a real map — every UF gets the same visual real estate.
const UF_GRID: Record<string, [number, number]> = {
  // Row 0 — extremos do Norte
  RR: [4, 0],
  AP: [6, 0],
  // Row 1 — Norte central + Nordeste arco superior
  AM: [3, 1], PA: [5, 1], MA: [6, 1], CE: [7, 1], RN: [8, 1],
  // Row 2 — Norte sudoeste + Nordeste meio
  AC: [2, 2], RO: [3, 2], TO: [5, 2], PI: [6, 2], PB: [8, 2],
  // Row 3 — Centro-Oeste norte + Nordeste leste
  MT: [4, 3], BA: [6, 3], PE: [7, 3], AL: [8, 3],
  // Row 4 — Centro-Oeste sul + Nordeste sul
  MS: [3, 4], GO: [5, 4], DF: [6, 4], SE: [8, 4],
  // Row 5 — Sudeste norte
  MG: [6, 5], ES: [7, 5],
  // Row 6 — Sudeste sul
  SP: [5, 6], RJ: [6, 6],
  // Rows 7-9 — Sul (norte → sul)
  PR: [4, 7],
  SC: [4, 8],
  RS: [4, 9],
};

const TILE = 50;
const GAP = 4;
const COLS = 9;
const ROWS = 10;
const VIEW_W = COLS * (TILE + GAP) + GAP;
const VIEW_H = ROWS * (TILE + GAP) + GAP;

// ── Cluster colors — same palette as the scatter and similar-voters ─────
function clusterFill(label: string | null | undefined): string {
  if (!label) return "#94a3b8"; // gray
  const l = label.toLowerCase();
  if (/coaliz[aã]o\s+govern/.test(l)) return "#1B4332"; // cerrado
  if (/centr[aã]o/.test(l))           return "#C17D3C"; // ochre
  if (/bolsonar/.test(l))             return "#1A1F2E"; // brasilia
  if (l === "misto")                  return "#7A6F5C"; // warm gray
  return "#94a3b8";
}
function clusterChipClass(label: string | null | undefined): string {
  if (!label) return "bg-gray-300 text-brasilia";
  const l = label.toLowerCase();
  if (/coaliz[aã]o\s+govern/.test(l)) return "bg-cerrado text-white";
  if (/centr[aã]o/.test(l))           return "bg-ochre text-white";
  if (/bolsonar/.test(l))             return "bg-brasilia text-white";
  if (l === "misto")                  return "bg-text-warm/30 text-brasilia";
  return "bg-gray-300 text-brasilia";
}

const UF_NAMES: Record<string, string> = {
  AC: "Acre", AL: "Alagoas", AP: "Amapá", AM: "Amazonas", BA: "Bahia",
  CE: "Ceará", DF: "Distrito Federal", ES: "Espírito Santo", GO: "Goiás",
  MA: "Maranhão", MT: "Mato Grosso", MS: "Mato Grosso do Sul",
  MG: "Minas Gerais", PA: "Pará", PB: "Paraíba", PR: "Paraná",
  PE: "Pernambuco", PI: "Piauí", RJ: "Rio de Janeiro",
  RN: "Rio Grande do Norte", RS: "Rio Grande do Sul", RO: "Rondônia",
  RR: "Roraima", SC: "Santa Catarina", SP: "São Paulo", SE: "Sergipe",
  TO: "Tocantins",
};

// ── Component ──────────────────────────────────────────────────────────────
export default function StateMap({ profiles }: { profiles: StateProfile[] }) {
  const byUf = useMemo(() => {
    const m = new Map<string, StateProfile>();
    for (const p of profiles) m.set(p.uf, p);
    return m;
  }, [profiles]);

  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<{ uf: string; x: number; y: number } | null>(null);

  const selectedProfile = selected ? byUf.get(selected) ?? null : null;
  const hoveredProfile  = hovered  ? byUf.get(hovered.uf) ?? null  : null;

  // Auto-insights from full population — these stay constant regardless of selection.
  const insights = useMemo(() => {
    const withScore = profiles.filter((p) => p.avg_const_alignment != null);
    const topConst = [...withScore]
      .sort((a, b) => (b.avg_const_alignment! - a.avg_const_alignment!))
      .slice(0, 3);
    // Bolsonarista presence as % of state delegation
    const topBolso = [...profiles]
      .map((p) => {
        const bolso = p.clusters.find((c) => /bolsonar/i.test(c.cluster_label));
        const pct = bolso && p.deputy_count > 0
          ? (bolso.deputy_count / p.deputy_count) * 100
          : 0;
        return { uf: p.uf, pct, count: bolso?.deputy_count ?? 0 };
      })
      .filter((s) => s.pct > 0)
      .sort((a, b) => b.pct - a.pct)
      .slice(0, 3);
    return { topConst, topBolso };
  }, [profiles]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-6 lg:gap-8">
      {/* ── Map card ─────────────────────────────────────────────── */}
      <div>
        <div className="bg-white rounded-lg border border-concreto-shadow shadow-sm p-4 sm:p-6 relative">
          <div className="overflow-x-auto">
            <svg
              viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
              width="100%"
              style={{ maxWidth: VIEW_W, display: "block", margin: "0 auto" }}
              role="img"
              aria-label="Mapa do Brasil — distribuição de coalizões comportamentais por estado"
            >
              {Object.entries(UF_GRID).map(([uf, [c, r]]) => {
                const profile = byUf.get(uf);
                const fill = clusterFill(profile?.dominant_cluster);
                const isSelected = selected === uf;
                const isHovered  = hovered?.uf === uf;
                const x = GAP + c * (TILE + GAP);
                const y = GAP + r * (TILE + GAP);
                return (
                  <g
                    key={uf}
                    transform={`translate(${x}, ${y})`}
                    onMouseEnter={(e) =>
                      setHovered({ uf, x: e.clientX, y: e.clientY })
                    }
                    onMouseMove={(e) =>
                      setHovered((h) =>
                        h?.uf === uf ? { ...h, x: e.clientX, y: e.clientY } : h,
                      )
                    }
                    onMouseLeave={() =>
                      setHovered((h) => (h?.uf === uf ? null : h))
                    }
                    onClick={() => setSelected((cur) => (cur === uf ? null : uf))}
                    style={{ cursor: profile ? "pointer" : "default" }}
                    aria-label={`${UF_NAMES[uf]}: ${profile?.deputy_count ?? 0} deputados`}
                  >
                    <rect
                      width={TILE}
                      height={TILE}
                      rx={6}
                      fill={fill}
                      opacity={profile ? (isSelected ? 1 : isHovered ? 0.95 : 0.85) : 0.25}
                      stroke={isSelected ? "#E8B84B" : "#FFFFFF"}
                      strokeWidth={isSelected ? 2.5 : 1}
                    />
                    <text
                      x={TILE / 2}
                      y={TILE / 2 - 2}
                      textAnchor="middle"
                      dominantBaseline="middle"
                      fill={fill === "#94a3b8" ? "#1A1F2E" : "#FFFFFF"}
                      style={{
                        fontFamily: "var(--font-jetbrains)",
                        fontSize: 13,
                        fontWeight: 700,
                        pointerEvents: "none",
                      }}
                    >
                      {uf}
                    </text>
                    {profile && (
                      <text
                        x={TILE / 2}
                        y={TILE / 2 + 12}
                        textAnchor="middle"
                        dominantBaseline="middle"
                        fill={fill === "#94a3b8" ? "#1A1F2E" : "#FFFFFF"}
                        style={{
                          fontFamily: "var(--font-jetbrains)",
                          fontSize: 9,
                          fontWeight: 500,
                          opacity: 0.85,
                          pointerEvents: "none",
                        }}
                      >
                        {profile.deputy_count}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>
          </div>

          {/* Map legend */}
          <div className="mt-4 pt-4 border-t border-concreto-shadow flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-text-warm">
            <span className="font-display font-bold text-[10px] uppercase tracking-widest text-brasilia">
              Coalizão dominante
            </span>
            {[
              ["Coalização Governista", "#1B4332"],
              ["Centrão Governista",    "#C17D3C"],
              ["Bloco Bolsonarista",    "#1A1F2E"],
              ["Misto (sem dominante)", "#7A6F5C"],
            ].map(([label, color]) => (
              <span key={label} className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block w-3 h-3 rounded-sm"
                  style={{ backgroundColor: color as string }}
                />
                {label}
              </span>
            ))}
            <span className="ml-auto text-[10px] italic">
              Clique em um estado para ver detalhes
            </span>
          </div>
        </div>

        {/* ── Auto-generated insights ────────────────────────────── */}
        <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <article className="bg-white rounded-lg border border-concreto-shadow border-l-[3px] border-l-cerrado p-4">
            <p className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
              Maior alinhamento com a CF/88
            </p>
            <ol className="mt-2 space-y-1 text-sm">
              {insights.topConst.map((p, i) => (
                <li key={p.uf} className="flex items-baseline gap-2">
                  <span className="font-mono text-text-warm w-4">{i + 1}.</span>
                  <span className="font-display font-bold text-brasilia">
                    {UF_NAMES[p.uf] ?? p.uf}
                  </span>
                  <span className="ml-auto font-mono text-cerrado text-xs">
                    {p.avg_const_alignment! > 0 ? "+" : ""}
                    {p.avg_const_alignment!.toFixed(2)}
                  </span>
                </li>
              ))}
            </ol>
          </article>

          <article className="bg-white rounded-lg border border-concreto-shadow border-l-[3px] border-l-brasilia p-4">
            <p className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
              Maior presença bolsonarista
            </p>
            <ol className="mt-2 space-y-1 text-sm">
              {insights.topBolso.length === 0 ? (
                <li className="text-text-warm italic text-xs">
                  Nenhum estado com presença bolsonarista identificada.
                </li>
              ) : (
                insights.topBolso.map((s, i) => (
                  <li key={s.uf} className="flex items-baseline gap-2">
                    <span className="font-mono text-text-warm w-4">{i + 1}.</span>
                    <span className="font-display font-bold text-brasilia">
                      {UF_NAMES[s.uf] ?? s.uf}
                    </span>
                    <span className="ml-auto font-mono text-brasilia text-xs">
                      {Math.round(s.pct)}% ({s.count})
                    </span>
                  </li>
                ))
              )}
            </ol>
          </article>
        </div>
      </div>

      {/* ── Side panel (desktop) / modal (mobile) ─────────────── */}
      <aside className="hidden lg:block">
        {selectedProfile ? (
          <DetailPanel profile={selectedProfile} onClose={() => setSelected(null)} />
        ) : (
          <div className="bg-white rounded-lg border border-concreto-shadow p-6 text-center text-text-warm h-full flex flex-col justify-center">
            <p className="text-sm">
              Clique em um estado no mapa para ver sua delegação na Câmara
              dos Deputados.
            </p>
            <p className="text-xs mt-2 italic text-text-warm/70">
              São Paulo, Minas Gerais e Rio Grande do Sul são os estados com
              maior número de deputados — bons pontos de partida.
            </p>
          </div>
        )}
      </aside>

      {/* Mobile modal — only renders when something is selected */}
      {selectedProfile && (
        <div
          className="lg:hidden fixed inset-0 z-50 bg-brasilia/60 flex items-end sm:items-center justify-center p-3 sm:p-6"
          onClick={() => setSelected(null)}
        >
          <div
            className="bg-white rounded-lg max-w-md w-full max-h-[85vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <DetailPanel profile={selectedProfile} onClose={() => setSelected(null)} />
          </div>
        </div>
      )}

      {/* Cursor-following hover tooltip */}
      {hoveredProfile && hovered && (
        <div
          className="fixed z-40 pointer-events-none bg-brasilia text-white text-xs rounded-md shadow-lg px-2.5 py-2 max-w-[220px]"
          style={{ left: hovered.x + 14, top: hovered.y + 14 }}
        >
          <p className="font-display font-bold leading-tight">
            {UF_NAMES[hoveredProfile.uf] ?? hoveredProfile.uf}
          </p>
          <p className="text-gray-300 text-[10px] mt-0.5">
            <span className="font-mono">{hoveredProfile.deputy_count}</span> deputados
          </p>
          {hoveredProfile.dominant_cluster && (
            <p className="text-[10px] mt-1 text-ipe">
              {hoveredProfile.dominant_cluster}{" "}
              {hoveredProfile.dominant_cluster !== "Misto" ? "dominante" : ""}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Detail panel ──────────────────────────────────────────────────────────
function DetailPanel({
  profile,
  onClose,
}: {
  profile: StateProfile;
  onClose: () => void;
}) {
  const fmtPct = (x: number | null) =>
    x == null ? "—" : `${Math.round(x * 100)}%`;
  const fmtConst = (x: number | null) =>
    x == null ? "—" : `${x > 0 ? "+" : ""}${x.toFixed(2)}`;
  const fullName = UF_NAMES[profile.uf] ?? profile.uf;
  // Max for cluster bars
  const maxClusterCount = profile.clusters.reduce(
    (m, c) => (c.deputy_count > m ? c.deputy_count : m),
    0,
  );

  return (
    <div className="bg-white rounded-lg border border-concreto-shadow shadow-sm overflow-hidden">
      {/* Header */}
      <header className="bg-brasilia text-white px-4 py-3 flex items-start justify-between">
        <div>
          <p className="font-display font-bold text-lg leading-none">{fullName}</p>
          <p className="text-xs text-gray-300 mt-1">
            <span className="font-mono">{profile.deputy_count}</span> deputados
            federais
            {profile.dominant_cluster && profile.dominant_cluster !== "Misto" && (
              <>
                {" · "}
                <span className="text-ipe">
                  {profile.dominant_cluster} dominante
                </span>
              </>
            )}
          </p>
        </div>
        <button
          onClick={onClose}
          className="text-gray-300 hover:text-white text-lg leading-none"
          aria-label="Fechar"
        >
          ×
        </button>
      </header>

      <div className="p-4 space-y-5">
        {/* Cluster distribution */}
        <section>
          <h3 className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest mb-2">
            Distribuição por coalizão
          </h3>
          <div className="space-y-1.5">
            {profile.clusters.map((c) => {
              const w = maxClusterCount > 0
                ? (c.deputy_count / maxClusterCount) * 100
                : 0;
              return (
                <div
                  key={`${c.cluster_id}-${c.cluster_label}`}
                  className="flex items-center gap-2 text-xs"
                >
                  <span className="w-32 truncate text-brasilia">
                    {c.cluster_label}
                  </span>
                  <div className="flex-1 h-2 bg-concreto-shadow rounded-full overflow-hidden">
                    <div
                      className="h-full"
                      style={{
                        width: `${w}%`,
                        backgroundColor: clusterFill(c.cluster_label),
                      }}
                    />
                  </div>
                  <span className="font-mono text-brasilia w-7 text-right">
                    {c.deputy_count}
                  </span>
                </div>
              );
            })}
          </div>
        </section>

        {/* Averaged scores */}
        <section>
          <h3 className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest mb-2">
            Indicadores médios
          </h3>
          <dl className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-concreto rounded-md p-2">
              <dt className="text-[9px] text-text-warm uppercase tracking-wider">
                CF/88
              </dt>
              <dd className="font-mono text-base font-bold text-brasilia mt-0.5">
                {fmtConst(profile.avg_const_alignment)}
              </dd>
            </div>
            <div className="bg-concreto rounded-md p-2">
              <dt className="text-[9px] text-text-warm uppercase tracking-wider">
                Disciplina
              </dt>
              <dd className="font-mono text-base font-bold text-brasilia mt-0.5">
                {fmtPct(profile.avg_discipline)}
              </dd>
            </div>
            <div className="bg-concreto rounded-md p-2">
              <dt className="text-[9px] text-text-warm uppercase tracking-wider">
                Ausência
              </dt>
              <dd className="font-mono text-base font-bold text-brasilia mt-0.5">
                {fmtPct(profile.avg_absence)}
              </dd>
            </div>
          </dl>
        </section>

        {/* Top deputies */}
        <section>
          <h3 className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest mb-2">
            Deputados desta UF
            <span className="ml-1 normal-case font-normal tracking-normal text-text-warm/70">
              (maior alinhamento CF/88)
            </span>
          </h3>
          <ul className="space-y-1.5">
            {profile.top_deputies.map((d) => (
              <li key={d.id}>
                <Link
                  href={`/deputados/${d.id}`}
                  className="flex items-center gap-2.5 p-1.5 rounded-md hover:bg-concreto transition-colors group"
                >
                  {d.photo_url ? (
                    <Image
                      src={d.photo_url}
                      alt=""
                      width={32}
                      height={32}
                      className="rounded-full bg-concreto-shadow object-cover shrink-0"
                      unoptimized
                    />
                  ) : (
                    <div className="w-8 h-8 rounded-full bg-concreto-shadow flex items-center justify-center text-xs text-text-warm font-display shrink-0">
                      {(d.name[0] ?? "?").toUpperCase()}
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-brasilia truncate font-medium group-hover:text-cerrado">
                      {d.name}
                    </p>
                    <p className="text-[10px] text-text-warm font-mono">
                      {d.party ?? "—"}
                    </p>
                  </div>
                  <span
                    className={`text-[9px] px-1.5 py-0.5 rounded-full shrink-0 ${clusterChipClass(d.cluster_label)}`}
                  >
                    {d.cluster_label ?? "—"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <Link
            href={`/deputados?state=${profile.uf}`}
            className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-cerrado hover:text-ochre transition-colors"
          >
            Ver todos os {profile.deputy_count} deputados →
          </Link>
        </section>

        {/* Parties */}
        {profile.parties.length > 0 && (
          <section>
            <h3 className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest mb-2">
              Partidos representados ({profile.parties.length})
            </h3>
            <p className="text-[11px] text-text-warm font-mono leading-relaxed">
              {profile.parties.join(" · ")}
            </p>
          </section>
        )}
      </div>
    </div>
  );
}

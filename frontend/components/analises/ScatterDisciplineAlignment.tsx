"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { ScatterPoint } from "@/lib/api";

// ── Cluster → color mapping ────────────────────────────────────────────────
// Matches by case-insensitive keyword in cluster_label so the visual
// stays correct even if the analyst rewords a cluster on re-cluster.
type ClusterStyle = { color: string; chip: string; label: string };

const CLUSTER_PALETTE: { match: RegExp; style: ClusterStyle }[] = [
  {
    match: /coaliz[aã]o\s+govern|coalizao\s+govern/i,
    style: { color: "#1B4332", chip: "bg-cerrado text-white", label: "Coalizão Governista" },
  },
  {
    match: /centr[aã]o/i,
    style: { color: "#C17D3C", chip: "bg-ochre text-white", label: "Centrão Governista" },
  },
  {
    match: /bolsonar/i,
    style: { color: "#1A1F2E", chip: "bg-brasilia text-white", label: "Bloco Bolsonarista" },
  },
];
const NO_CLUSTER: ClusterStyle = {
  color: "#94a3b8",
  chip: "bg-gray-300 text-brasilia",
  label: "Sem cluster",
};

function styleFor(label: string | null): ClusterStyle {
  if (!label) return NO_CLUSTER;
  for (const { match, style } of CLUSTER_PALETTE) if (match.test(label)) return style;
  // Unknown cluster — fall back to grey but keep the original label visible.
  return { ...NO_CLUSTER, label };
}

// ── Chart geometry ─────────────────────────────────────────────────────────
const W = 720;
const H = 460;
const M = { top: 24, right: 24, bottom: 56, left: 60 };
const PW = W - M.left - M.right;
const PH = H - M.top - M.bottom;

// X: discipline in [0, 1]. Y: const_alignment in [-1, +1].
const xScale = (d: number) => M.left + d * PW;
const yScale = (a: number) => M.top + ((1 - a) / 2) * PH;

// Quadrant detector — uses chart-domain midpoints (discipline=0.5, const=0).
type Quadrant = "TR" | "TL" | "BR" | "BL";
function quadrantOf(p: ScatterPoint): Quadrant {
  const right = p.discipline >= 0.5;
  const top = p.const_alignment >= 0;
  return (top ? (right ? "TR" : "TL") : right ? "BR" : "BL") as Quadrant;
}

const QUADRANT_META: Record<
  Quadrant,
  { title: string; emoji: string; tint: string; cardBorder: string }
> = {
  TR: {
    title: "Disciplinado + Constitucional",
    emoji: "🟢",
    tint: "rgba(27, 67, 50, 0.04)",
    cardBorder: "border-l-cerrado",
  },
  TL: {
    title: "Independente + Constitucional",
    emoji: "🟡",
    tint: "rgba(193, 125, 60, 0.03)",
    cardBorder: "border-l-ochre",
  },
  BR: {
    title: "Disciplinado + Anticonstitucional",
    emoji: "🔴",
    tint: "rgba(192, 57, 43, 0.05)",
    cardBorder: "border-l-[#C0392B]",
  },
  BL: {
    title: "Independente + Anticonstitucional",
    emoji: "⚪",
    tint: "rgba(148, 163, 184, 0.06)",
    cardBorder: "border-l-text-warm",
  },
};

// Quadrant rect geometry (for the pale tints)
const QUADRANT_RECTS: Record<Quadrant, { x: number; y: number; w: number; h: number }> = {
  TL: { x: M.left, y: M.top, w: PW / 2, h: PH / 2 },
  TR: { x: M.left + PW / 2, y: M.top, w: PW / 2, h: PH / 2 },
  BL: { x: M.left, y: M.top + PH / 2, w: PW / 2, h: PH / 2 },
  BR: { x: M.left + PW / 2, y: M.top + PH / 2, w: PW / 2, h: PH / 2 },
};

// ── Component ──────────────────────────────────────────────────────────────
export default function ScatterDisciplineAlignment({
  points,
}: {
  points: ScatterPoint[];
}) {
  // Filter UI state
  const [hiddenClusters, setHiddenClusters] = useState<Set<string>>(new Set());
  const [stateFilter, setStateFilter] = useState<string>("");
  const [partyFilter, setPartyFilter] = useState<string>("");
  const [highlightQuery, setHighlightQuery] = useState<string>("");

  // Hover state
  const [hovered, setHovered] = useState<ScatterPoint | null>(null);

  // Static derived sets
  const clusterOptions = useMemo(() => {
    const seen = new Map<string, ClusterStyle>();
    for (const p of points) {
      const key = p.cluster_label ?? "__none__";
      if (!seen.has(key)) seen.set(key, styleFor(p.cluster_label));
    }
    return Array.from(seen.entries()).map(([key, style]) => ({ key, style }));
  }, [points]);

  const stateOptions = useMemo(() => {
    const ufs = new Set<string>();
    for (const p of points) if (p.state_uf) ufs.add(p.state_uf);
    return Array.from(ufs).sort();
  }, [points]);

  // Apply filters
  const filtered = useMemo(() => {
    const partyQ = partyFilter.trim().toUpperCase();
    return points.filter((p) => {
      const clusterKey = p.cluster_label ?? "__none__";
      if (hiddenClusters.has(clusterKey)) return false;
      if (stateFilter && p.state_uf !== stateFilter) return false;
      if (partyQ && !(p.party ?? "").toUpperCase().includes(partyQ)) return false;
      return true;
    });
  }, [points, hiddenClusters, stateFilter, partyFilter]);

  // Highlight match — rendered last (on top) and grown
  const highlightedIds = useMemo(() => {
    const q = highlightQuery.trim().toLowerCase();
    if (!q) return new Set<string>();
    return new Set(
      filtered
        .filter((p) => p.name.toLowerCase().includes(q))
        .map((p) => p.id),
    );
  }, [filtered, highlightQuery]);

  const toggleCluster = (key: string) =>
    setHiddenClusters((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  // Quadrant insights from the *filtered* set so they stay coherent with
  // what's visible on the chart.
  const insights = useMemo(() => {
    const acc: Record<
      Quadrant,
      { count: number; parties: Map<string, number>; extreme: ScatterPoint | null }
    > = {
      TR: { count: 0, parties: new Map(), extreme: null },
      TL: { count: 0, parties: new Map(), extreme: null },
      BR: { count: 0, parties: new Map(), extreme: null },
      BL: { count: 0, parties: new Map(), extreme: null },
    };
    for (const p of filtered) {
      const q = quadrantOf(p);
      acc[q].count++;
      if (p.party) acc[q].parties.set(p.party, (acc[q].parties.get(p.party) ?? 0) + 1);
      // "Extreme" = farthest from origin in the chart's normalized space.
      // Discipline normalized 0..1 around 0.5 → distance |d-0.5|*2; const
      // is already -1..1. Sum of absolute values gives a quadrant-corner
      // ordering that's intuitive: most disciplined AND most aligned.
      const score = Math.abs(p.discipline - 0.5) * 2 + Math.abs(p.const_alignment);
      const cur = acc[q].extreme;
      const curScore = cur
        ? Math.abs(cur.discipline - 0.5) * 2 + Math.abs(cur.const_alignment)
        : -Infinity;
      if (score > curScore) acc[q].extreme = p;
    }
    return (Object.entries(acc) as [Quadrant, (typeof acc)[Quadrant]][]).map(
      ([q, v]) => ({
        quadrant: q,
        count: v.count,
        topParties: Array.from(v.parties.entries())
          .sort((a, b) => b[1] - a[1])
          .slice(0, 3)
          .map(([name]) => name),
        extreme: v.extreme,
      }),
    );
  }, [filtered]);

  return (
    <div className="space-y-6">
      {/* ── Filters ──────────────────────────────────────────────────── */}
      <details className="bg-white rounded-lg border border-concreto-shadow p-4 sm:p-5 group" open>
        <summary className="cursor-pointer font-display font-bold text-brasilia text-base flex items-center justify-between sm:cursor-default sm:list-none">
          <span>Filtros</span>
          <span className="text-xs text-text-warm sm:hidden group-open:hidden">
            tocar para abrir
          </span>
        </summary>

        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
          {/* Cluster */}
          <fieldset>
            <legend className="text-[11px] font-display font-bold text-text-warm uppercase tracking-wider mb-1.5">
              Cluster
            </legend>
            <div className="space-y-1.5">
              {clusterOptions.map(({ key, style }) => {
                const visible = !hiddenClusters.has(key);
                return (
                  <label
                    key={key}
                    className="flex items-center gap-2 cursor-pointer text-brasilia"
                  >
                    <input
                      type="checkbox"
                      checked={visible}
                      onChange={() => toggleCluster(key)}
                      className="accent-cerrado"
                    />
                    <span
                      className="inline-block w-2.5 h-2.5 rounded-full"
                      style={{ backgroundColor: style.color }}
                    />
                    <span className="text-xs">{style.label}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          {/* UF */}
          <div>
            <label className="block text-[11px] font-display font-bold text-text-warm uppercase tracking-wider mb-1.5">
              Estado
            </label>
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="w-full bg-white border border-concreto-shadow rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-cerrado"
            >
              <option value="">Todos</option>
              {stateOptions.map((uf) => (
                <option key={uf} value={uf}>
                  {uf}
                </option>
              ))}
            </select>
          </div>

          {/* Party */}
          <div>
            <label className="block text-[11px] font-display font-bold text-text-warm uppercase tracking-wider mb-1.5">
              Partido
            </label>
            <input
              type="text"
              value={partyFilter}
              onChange={(e) => setPartyFilter(e.target.value)}
              placeholder="ex.: PT, PL, UNIÃO"
              className="w-full bg-white border border-concreto-shadow rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-cerrado"
            />
          </div>

          {/* Highlight */}
          <div>
            <label className="block text-[11px] font-display font-bold text-text-warm uppercase tracking-wider mb-1.5">
              Destacar deputado
            </label>
            <input
              type="text"
              value={highlightQuery}
              onChange={(e) => setHighlightQuery(e.target.value)}
              placeholder="nome ou parte do nome"
              className="w-full bg-white border border-concreto-shadow rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-cerrado"
            />
          </div>
        </div>

        {/* Counts */}
        <p className="mt-3 text-xs text-text-warm">
          Exibindo <span className="font-mono font-semibold text-brasilia">{filtered.length}</span>{" "}
          de <span className="font-mono">{points.length}</span> deputados
          {highlightedIds.size > 0 && (
            <>
              {" · "}
              <span className="font-mono text-cerrado">{highlightedIds.size}</span> destacado(s)
            </>
          )}
        </p>
      </details>

      {/* ── Chart ───────────────────────────────────────────────────── */}
      <div className="bg-white rounded-lg border border-concreto-shadow shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <div style={{ minWidth: W, position: "relative" }}>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              width="100%"
              height={H}
              className="block"
              role="img"
              aria-label="Gráfico de dispersão: disciplina partidária no eixo X, alinhamento constitucional no eixo Y"
            >
              {/* Background */}
              <rect x={0} y={0} width={W} height={H} fill="#F7F4EF" />

              {/* Quadrant tints */}
              {(["TR", "TL", "BR", "BL"] as Quadrant[]).map((q) => {
                const r = QUADRANT_RECTS[q];
                return (
                  <rect
                    key={q}
                    x={r.x}
                    y={r.y}
                    width={r.w}
                    height={r.h}
                    fill={QUADRANT_META[q].tint}
                  />
                );
              })}

              {/* Grid lines (faint) */}
              {[0.25, 0.75].map((v) => (
                <line
                  key={`vx-${v}`}
                  x1={xScale(v)}
                  x2={xScale(v)}
                  y1={M.top}
                  y2={M.top + PH}
                  stroke="#E5E0D6"
                  strokeWidth={1}
                />
              ))}
              {[-0.5, 0.5].map((v) => (
                <line
                  key={`hy-${v}`}
                  x1={M.left}
                  x2={M.left + PW}
                  y1={yScale(v)}
                  y2={yScale(v)}
                  stroke="#E5E0D6"
                  strokeWidth={1}
                />
              ))}

              {/* Reference lines (midpoints) */}
              <line
                x1={xScale(0.5)}
                x2={xScale(0.5)}
                y1={M.top}
                y2={M.top + PH}
                stroke="#1A1F2E"
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.45}
              />
              <line
                x1={M.left}
                x2={M.left + PW}
                y1={yScale(0)}
                y2={yScale(0)}
                stroke="#1A1F2E"
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.45}
              />

              {/* Axes (solid) */}
              <line
                x1={M.left}
                x2={M.left}
                y1={M.top}
                y2={M.top + PH}
                stroke="#1A1F2E"
                strokeWidth={1.5}
              />
              <line
                x1={M.left}
                x2={M.left + PW}
                y1={M.top + PH}
                y2={M.top + PH}
                stroke="#1A1F2E"
                strokeWidth={1.5}
              />

              {/* X tick labels (0%, 25%, 50%, 75%, 100%) */}
              {[0, 0.25, 0.5, 0.75, 1].map((v) => (
                <text
                  key={`xt-${v}`}
                  x={xScale(v)}
                  y={M.top + PH + 16}
                  textAnchor="middle"
                  className="fill-text-warm"
                  style={{ fontFamily: "var(--font-jetbrains)", fontSize: 10 }}
                >
                  {Math.round(v * 100)}%
                </text>
              ))}
              {/* Y tick labels (-1, -0.5, 0, +0.5, +1) */}
              {[-1, -0.5, 0, 0.5, 1].map((v) => (
                <text
                  key={`yt-${v}`}
                  x={M.left - 8}
                  y={yScale(v) + 3}
                  textAnchor="end"
                  className="fill-text-warm"
                  style={{ fontFamily: "var(--font-jetbrains)", fontSize: 10 }}
                >
                  {v > 0 ? `+${v}` : v}
                </text>
              ))}

              {/* Axis titles */}
              <text
                x={M.left + PW / 2}
                y={H - 14}
                textAnchor="middle"
                className="fill-brasilia"
                style={{ fontFamily: "var(--font-inter)", fontSize: 12, fontWeight: 600 }}
              >
                Disciplina partidária →
              </text>
              <text
                transform={`translate(16, ${M.top + PH / 2}) rotate(-90)`}
                textAnchor="middle"
                className="fill-brasilia"
                style={{ fontFamily: "var(--font-inter)", fontSize: 12, fontWeight: 600 }}
              >
                Alinhamento com a CF/88 →
              </text>

              {/* Quadrant labels (inside the plot, faded) */}
              {(
                [
                  ["TR", "Disciplinado + Constitucional", "end", -8, 14],
                  ["TL", "Independente + Constitucional", "start", 8, 14],
                  ["BR", "Disciplinado + Anticonstitucional", "end", -8, -8],
                  ["BL", "Independente + Anticonstitucional", "start", 8, -8],
                ] as [Quadrant, string, "start" | "end", number, number][]
              ).map(([q, label, anchor, dx, dy]) => {
                const r = QUADRANT_RECTS[q];
                const x = anchor === "end" ? r.x + r.w + dx : r.x + dx;
                const y = dy < 0 ? r.y + r.h + dy : r.y + dy;
                return (
                  <text
                    key={`ql-${q}`}
                    x={x}
                    y={y}
                    textAnchor={anchor}
                    className="fill-text-warm"
                    style={{ fontFamily: "var(--font-inter)", fontSize: 10, opacity: 0.55 }}
                  >
                    {label}
                  </text>
                );
              })}

              {/* Dots — non-highlighted first, highlighted last (on top) */}
              {filtered
                .filter((p) => !highlightedIds.has(p.id))
                .map((p) => {
                  const style = styleFor(p.cluster_label);
                  const isHover = hovered?.id === p.id;
                  return (
                    <circle
                      key={p.id}
                      cx={xScale(p.discipline)}
                      cy={yScale(p.const_alignment)}
                      r={isHover ? 10 : 6}
                      fill={style.color}
                      opacity={isHover ? 1 : 0.7}
                      stroke="#fff"
                      strokeWidth={isHover ? 1.5 : 0.6}
                      className="cursor-pointer transition-[r,opacity]"
                      onMouseEnter={() => setHovered(p)}
                      onMouseLeave={() =>
                        setHovered((cur) => (cur?.id === p.id ? null : cur))
                      }
                      onClick={() => {
                        // Use location.href so this works even if the parent
                        // forgot to provide a router context.
                        window.location.href = `/deputados/${p.id}`;
                      }}
                    >
                      <title>{`${p.name} (${p.party ?? "—"}/${p.state_uf ?? "—"})`}</title>
                    </circle>
                  );
                })}

              {/* Highlighted dots + persistent labels */}
              {filtered
                .filter((p) => highlightedIds.has(p.id))
                .map((p) => {
                  const style = styleFor(p.cluster_label);
                  const cx = xScale(p.discipline);
                  const cy = yScale(p.const_alignment);
                  return (
                    <g key={`h-${p.id}`}>
                      <circle
                        cx={cx}
                        cy={cy}
                        r={16}
                        fill={style.color}
                        opacity={0.25}
                      />
                      <circle
                        cx={cx}
                        cy={cy}
                        r={10}
                        fill={style.color}
                        stroke="#fff"
                        strokeWidth={2}
                        className="cursor-pointer"
                        onMouseEnter={() => setHovered(p)}
                        onMouseLeave={() =>
                          setHovered((cur) => (cur?.id === p.id ? null : cur))
                        }
                        onClick={() => {
                          window.location.href = `/deputados/${p.id}`;
                        }}
                      >
                        <title>{`${p.name} (${p.party ?? "—"}/${p.state_uf ?? "—"})`}</title>
                      </circle>
                      <text
                        x={cx + 14}
                        y={cy + 4}
                        textAnchor="start"
                        className="fill-brasilia"
                        style={{
                          fontFamily: "var(--font-inter)",
                          fontSize: 11,
                          fontWeight: 700,
                          paintOrder: "stroke fill",
                          stroke: "#fff",
                          strokeWidth: 3,
                        }}
                      >
                        {p.name}
                      </text>
                    </g>
                  );
                })}
            </svg>

            {/* HTML overlay tooltip — keeps text crisp + lets us style with Tailwind */}
            {hovered && (
              <div
                className="pointer-events-none absolute bg-brasilia text-white text-xs rounded-md shadow-lg p-2.5 max-w-[260px]"
                style={{
                  // Convert SVG viewBox coords to overlay px (responsive width)
                  // by using percentages on left, then nudging.
                  left: `${(xScale(hovered.discipline) / W) * 100}%`,
                  top: `${(yScale(hovered.const_alignment) / H) * 100}%`,
                  transform: "translate(14px, -50%)",
                }}
              >
                <p className="font-bold leading-tight">{hovered.name}</p>
                <p className="text-gray-300 text-[10px] mt-0.5">
                  {(hovered.party ?? "—")} · {hovered.state_uf ?? "—"}
                </p>
                <span
                  className={`inline-block mt-1.5 text-[9px] px-1.5 py-0.5 rounded-full ${styleFor(hovered.cluster_label).chip}`}
                >
                  {styleFor(hovered.cluster_label).label}
                </span>
                <div className="mt-1.5 space-y-0.5 font-mono text-[10px]">
                  <p>
                    Disciplina:{" "}
                    <span className="text-ipe">
                      {Math.round(hovered.discipline * 100)}%
                    </span>
                  </p>
                  <p>
                    Alinhamento CF/88:{" "}
                    <span className="text-ipe">
                      {hovered.const_alignment > 0 ? "+" : ""}
                      {hovered.const_alignment.toFixed(2)}
                    </span>
                  </p>
                </div>
                <p className="mt-1.5 text-[9px] text-gray-400 italic">
                  clique para abrir o perfil →
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Cluster legend (under the chart, always-visible) */}
        <div className="border-t border-concreto-shadow px-4 py-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-text-warm">
          {clusterOptions.map(({ key, style }) => (
            <span key={`leg-${key}`} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: style.color }}
              />
              {style.label}
            </span>
          ))}
        </div>
      </div>

      {/* ── Quadrant insight cards ─────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {insights.map(({ quadrant, count, topParties, extreme }) => {
          const meta = QUADRANT_META[quadrant];
          return (
            <article
              key={quadrant}
              className={`bg-white rounded-lg border border-concreto-shadow border-l-[4px] ${meta.cardBorder} p-4`}
            >
              <p className="font-display font-bold text-brasilia text-sm flex items-center gap-1.5">
                <span aria-hidden>{meta.emoji}</span>
                {meta.title}
              </p>
              <p className="font-mono text-2xl font-bold text-brasilia mt-1">
                {count}
                <span className="text-xs text-text-warm font-normal font-sans ml-1.5">
                  deputados
                </span>
              </p>
              {topParties.length > 0 ? (
                <p className="text-xs text-text-warm mt-2">
                  Principais partidos:{" "}
                  <span className="font-semibold text-brasilia">
                    {topParties.join(", ")}
                  </span>
                </p>
              ) : (
                <p className="text-xs text-text-warm mt-2 italic">
                  Sem partidos identificados
                </p>
              )}
              {extreme ? (
                <p className="text-xs text-text-warm mt-1.5">
                  Caso extremo:{" "}
                  <Link
                    href={`/deputados/${extreme.id}`}
                    className="font-semibold text-cerrado hover:text-ochre transition-colors"
                  >
                    {extreme.name}
                  </Link>{" "}
                  <span className="text-text-warm/70">
                    ({extreme.party ?? "—"}/{extreme.state_uf ?? "—"})
                  </span>
                </p>
              ) : (
                <p className="text-xs text-text-warm mt-1.5 italic">
                  Quadrante vazio com os filtros atuais
                </p>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}

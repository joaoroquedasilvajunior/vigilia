"use client";

import { useMemo, useState } from "react";
import type { DonorVoteHeatmap as HeatmapData, HeatmapCell } from "@/lib/api";

// ── Pretty labels ──────────────────────────────────────────────────────────
// Both sector_group values (set by the donor classification pipeline) and
// theme tags (set by the bill tag pipeline) are kebab/snake-case slugs.
// The display layer hand-translates the common ones into Portuguese.
const SECTOR_LABELS: Record<string, string> = {
  financeiro:        "Financeiro",
  midia_tecnologia:  "Mídia & Tecnologia",
  religioso:         "Religioso",
  agronegocio:       "Agronegócio",
  agro:              "Agronegócio",
  construcao:        "Construção Civil",
  industria:         "Indústria",
  saude:             "Saúde",
  educacao:          "Educação",
  mineracao:         "Mineração",
  energia:           "Energia",
  transporte:        "Transporte",
  comercio:          "Comércio",
  servicos:          "Serviços",
};
const THEME_LABELS: Record<string, string> = {
  "reforma-politica":   "Reforma Política",
  "tributacao":         "Tributação",
  "trabalho":           "Trabalho",
  "seguranca-publica":  "Segurança Pública",
  "agronegocio":        "Agronegócio",
  "meio-ambiente":      "Meio Ambiente",
  "educacao":           "Educação",
  "saude":              "Saúde",
  "indigenas":          "Indígenas",
  "infraestrutura":     "Infraestrutura",
  "direitos-humanos":   "Direitos Humanos",
  "economia":           "Economia",
  "energia":            "Energia",
  "transporte":         "Transporte",
  "habitacao":          "Habitação",
  "previdencia":        "Previdência",
};

const prettySector = (s: string) =>
  SECTOR_LABELS[s] ?? s.replace(/[_-]/g, " ");
const prettyTheme = (t: string) =>
  THEME_LABELS[t] ?? t.replace(/[_-]/g, " ");

// ── "Sector matches theme" → ⚡ highlight rule ─────────────────────────────
// These are the politically loaded combinations where a high pct_sim from
// donors-of-the-sector voting on bills-in-the-theme is most worth flagging.
// Match is symmetric on sector tokens vs theme tokens, plus a curated list
// of cross-pairs that don't share a literal word but are sector-aligned in
// Brazilian politics.
const CROSS_MATCHES: Array<[RegExp, RegExp]> = [
  [/financeir/i,   /tributa/i],
  [/midia|tecnolog|tecno/i, /reforma-politica|midia/i],
  [/religios/i,    /educa|direitos|familia/i],
  [/agro|agroneg/i, /meio-?ambiente|indigen|agroneg/i],
  [/construc|imobil/i, /infraestrutura|habitac/i],
  [/mineracao|miner/i, /meio-?ambiente|indigen/i],
  [/saude|farmac/i, /saude/i],
  [/energia|petrol/i, /energia|meio-?ambiente/i],
  [/transport|combust/i, /transport|infraestrutura/i],
];

function isCrossMatch(sector: string, theme: string): boolean {
  // Direct word-overlap (e.g. "saude" sector × "saude" theme)
  const sTokens = sector.toLowerCase().split(/[_-]/);
  const tTokens = theme.toLowerCase().split(/[_-]/);
  if (sTokens.some((s) => tTokens.includes(s))) return true;
  return CROSS_MATCHES.some(
    ([s, t]) => s.test(sector) && t.test(theme),
  );
}

// ── Color scale ────────────────────────────────────────────────────────────
// White → cerrado green (#1B4332). HSL interpolation keeps the midtones from
// going muddy through grey. We also pull out a foreground color (white once
// the cell is dark enough to lose contrast).
function cellBg(pct: number): string {
  // Clamp to [0, 100] just in case
  const p = Math.max(0, Math.min(100, pct));
  // Use opacity over the cerrado swatch for a smooth gradient that still
  // reads as part of the brand palette.
  const alpha = (p / 100).toFixed(3);
  return `rgba(27, 67, 50, ${alpha})`;
}

function cellFg(pct: number): string {
  // White text once the cell is dark enough; brasilia (deep blue) otherwise.
  return pct >= 55 ? "#FFFFFF" : "#1A1F2E";
}

// ── Component ──────────────────────────────────────────────────────────────
export default function DonorVoteHeatmap({ data }: { data: HeatmapData }) {
  const { sectors, themes, cells } = data;

  // Build O(1) lookup
  const cellMap = useMemo(() => {
    const m = new Map<string, HeatmapCell>();
    for (const c of cells) m.set(`${c.sector}|${c.theme}`, c);
    return m;
  }, [cells]);

  const [hover, setHover] = useState<{
    sector: string;
    theme: string;
    cell: HeatmapCell | null;
    x: number;
    y: number;
  } | null>(null);

  if (sectors.length === 0 || themes.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-concreto-shadow p-8 text-center">
        <p className="text-text-warm">
          Sem células com amostra suficiente para o mapa.
        </p>
        <p className="text-xs text-text-warm/70 mt-2">
          Cada célula exige no mínimo 10 votos para evitar ruído estatístico.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-concreto-shadow shadow-sm overflow-hidden">
        <div className="overflow-x-auto relative">
          <table className="border-separate border-spacing-0">
            <thead>
              <tr>
                {/* Top-left empty corner (sticky on horizontal scroll) */}
                <th
                  scope="col"
                  className="sticky left-0 z-20 bg-white border-b border-r border-concreto-shadow p-2 text-left"
                  style={{ minWidth: 160 }}
                >
                  <span className="text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
                    Setor ↓ Tema →
                  </span>
                </th>
                {themes.map((t) => (
                  <th
                    key={t}
                    scope="col"
                    className="border-b border-concreto-shadow p-2 align-bottom"
                    style={{ minWidth: 80 }}
                  >
                    <span
                      className="block text-[10px] font-mono uppercase tracking-wider text-text-warm whitespace-nowrap"
                      style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}
                      title={t}
                    >
                      {prettyTheme(t)}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sectors.map((s, rowIdx) => (
                <tr key={s}>
                  <th
                    scope="row"
                    className={`sticky left-0 z-10 bg-white border-r border-concreto-shadow text-left p-2 text-sm font-display font-semibold text-brasilia ${
                      rowIdx > 0 ? "border-t border-concreto-shadow" : ""
                    }`}
                    style={{ minWidth: 160 }}
                  >
                    {prettySector(s)}
                  </th>
                  {themes.map((t) => {
                    const cell = cellMap.get(`${s}|${t}`) ?? null;
                    const pct = cell?.pct_sim ?? null;
                    const lit = cell !== null && pct !== null && pct > 70 && isCrossMatch(s, t);
                    const isHover =
                      hover?.sector === s && hover?.theme === t;

                    if (cell === null || pct === null) {
                      return (
                        <td
                          key={t}
                          className={`border-t border-concreto-shadow text-center align-middle text-text-warm/40 ${
                            isHover ? "ring-1 ring-text-warm/40" : ""
                          }`}
                          style={{
                            minWidth: 80,
                            height: 60,
                            background: "repeating-linear-gradient(45deg, #F7F4EF 0 6px, #FFFFFF 6px 12px)",
                          }}
                          onMouseEnter={(e) =>
                            setHover({
                              sector: s, theme: t, cell: null,
                              x: e.clientX, y: e.clientY,
                            })
                          }
                          onMouseMove={(e) =>
                            setHover((h) =>
                              h && h.sector === s && h.theme === t
                                ? { ...h, x: e.clientX, y: e.clientY }
                                : h,
                            )
                          }
                          onMouseLeave={() =>
                            setHover((h) =>
                              h?.sector === s && h?.theme === t ? null : h,
                            )
                          }
                          aria-label={`${prettySector(s)} × ${prettyTheme(t)}: amostra insuficiente`}
                        >
                          <span className="text-xs">—</span>
                        </td>
                      );
                    }

                    return (
                      <td
                        key={t}
                        className={`border-t border-concreto-shadow text-center align-middle relative cursor-default transition-shadow ${
                          isHover ? "ring-2 ring-brasilia/60 z-10" : ""
                        }`}
                        style={{
                          minWidth: 80,
                          height: 60,
                          background: cellBg(pct),
                          color: cellFg(pct),
                          // Lit cells get a gold inset "border" via box-shadow so
                          // we can keep the table border collapse clean.
                          boxShadow: lit
                            ? "inset 0 0 0 2px #E8B84B"
                            : undefined,
                        }}
                        onMouseEnter={(e) =>
                          setHover({
                            sector: s, theme: t, cell,
                            x: e.clientX, y: e.clientY,
                          })
                        }
                        onMouseMove={(e) =>
                          setHover((h) =>
                            h && h.sector === s && h.theme === t
                              ? { ...h, x: e.clientX, y: e.clientY }
                              : h,
                          )
                        }
                        onMouseLeave={() =>
                          setHover((h) =>
                            h?.sector === s && h?.theme === t ? null : h,
                          )
                        }
                      >
                        <span className="font-mono text-sm font-semibold">
                          {Math.round(pct)}%
                        </span>
                        {lit && (
                          <span
                            className="absolute top-1 right-1 text-[10px]"
                            aria-label="Setor alinhado com o tema"
                          >
                            ⚡
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Color legend */}
        <div className="border-t border-concreto-shadow px-4 py-3 flex flex-wrap items-center gap-3 text-xs text-text-warm">
          <span className="font-display font-bold text-brasilia text-[10px] uppercase tracking-widest">
            Escala
          </span>
          <div className="flex items-center gap-0">
            {[0, 25, 50, 75, 100].map((p) => (
              <span
                key={p}
                className="w-8 h-4 inline-block first:rounded-l last:rounded-r border-t border-b border-concreto-shadow first:border-l last:border-r"
                style={{ background: cellBg(p) }}
                title={`${p}% sim`}
              />
            ))}
          </div>
          <span className="font-mono">0% sim → 100% sim</span>
          <span className="ml-auto inline-flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-3 rounded-sm"
              style={{ boxShadow: "inset 0 0 0 2px #E8B84B", background: cellBg(80) }}
            />
            ⚡ correlação setor × tema (&gt;70% sim)
          </span>
        </div>
      </div>

      {/* Floating tooltip — follows the cursor across cells */}
      {hover && (
        <div
          className="fixed z-50 pointer-events-none bg-brasilia text-white text-xs rounded-md shadow-xl p-2.5 max-w-[280px]"
          style={{
            left: hover.x + 14,
            top:  hover.y + 14,
          }}
        >
          <p className="font-display font-bold leading-tight">
            {prettySector(hover.sector)} × {prettyTheme(hover.theme)}
          </p>
          {hover.cell ? (
            <>
              <p className="text-gray-300 text-[10px] mt-1">
                <span className="font-mono text-ipe">{hover.cell.deputies}</span>{" "}
                deputado{hover.cell.deputies === 1 ? "" : "s"} financiado{hover.cell.deputies === 1 ? "" : "s"} por este setor
              </p>
              <p className="mt-1.5 text-[11px] leading-snug">
                Votaram <strong className="text-ipe">SIM em {Math.round(hover.cell.pct_sim ?? 0)}%</strong>{" "}
                dos projetos sobre {prettyTheme(hover.theme).toLowerCase()}.
              </p>
              <p className="text-[10px] text-gray-400 mt-1.5 font-mono">
                {hover.cell.sim} sim · {hover.cell.nao} não · {hover.cell.total} votos
              </p>
            </>
          ) : (
            <p className="text-gray-300 text-[10px] mt-1 italic">
              Amostra insuficiente (&lt; 10 votos) — célula não exibida.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

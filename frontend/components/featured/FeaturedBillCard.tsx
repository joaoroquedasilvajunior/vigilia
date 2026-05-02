"use client";

import Link from "next/link";
import type { FeaturedBill } from "@/lib/api";

// Per-theme accent colors. Match the rest of the design system.
// Tema chip background + left-border-accent on hover use the same hue.
const THEME_STYLE: Record<string, { chipCls: string; accentCls: string; label: string }> = {
  "reforma-politica": {
    chipCls: "bg-brasilia text-white",
    accentCls: "group-hover:border-l-brasilia",
    label: "Reforma Política",
  },
  tributacao: {
    chipCls: "bg-ochre text-white",
    accentCls: "group-hover:border-l-ochre",
    label: "Tributação",
  },
  indigenas: {
    chipCls: "bg-cerrado text-white",
    accentCls: "group-hover:border-l-cerrado",
    label: "Povos Indígenas",
  },
  trabalho: {
    chipCls: "bg-cerrado text-white",
    accentCls: "group-hover:border-l-cerrado",
    label: "Trabalho",
  },
  "meio-ambiente": {
    chipCls: "bg-cerrado text-white",
    accentCls: "group-hover:border-l-cerrado",
    label: "Meio Ambiente",
  },
  "seguranca-publica": {
    chipCls: "bg-[#C0392B] text-white",
    accentCls: "group-hover:border-l-[#C0392B]",
    label: "Segurança Pública",
  },
};

function fmtBR(n: number): string {
  return new Intl.NumberFormat("pt-BR").format(n);
}

function RiskBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return null;
  if (score > 0.6)
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">
        ⚠️ Alto risco
      </span>
    );
  if (score >= 0.3)
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700 font-medium">
        Risco médio
      </span>
    );
  return (
    <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium">
      Baixo risco
    </span>
  );
}

function VoteBar({ bill }: { bill: FeaturedBill }) {
  const sim = bill.votes_sim ?? 0;
  const nao = bill.votes_nao ?? 0;
  const abst = (bill.votes_abstencao ?? 0) + (bill.votes_obstrucao ?? 0) + (bill.votes_ausente ?? 0);
  const total = sim + nao + abst;

  if (total === 0) {
    return (
      <p className="text-xs text-text-warm italic mt-2">
        Votos não disponíveis
      </p>
    );
  }

  const simPct = (sim / total) * 100;
  const naoPct = (nao / total) * 100;
  const abstPct = (abst / total) * 100;
  const rejected = nao > sim;

  return (
    <div>
      {/* Header row: section label + optional rejection badge */}
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-[10px] font-display font-bold text-text-warm uppercase tracking-wider">
          Votação no plenário
        </p>
        {rejected && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-bold uppercase tracking-wider">
            Rejeitada
          </span>
        )}
      </div>

      {/* Stacked horizontal bar */}
      <div className="h-3 bg-concreto-shadow rounded-full overflow-hidden flex">
        {simPct > 0 && (
          <div
            className="bg-cerrado"
            style={{ width: `${simPct}%` }}
            aria-label={`${sim} sim`}
          />
        )}
        {naoPct > 0 && (
          <div
            className="bg-[#C0392B]"
            style={{ width: `${naoPct}%` }}
            aria-label={`${nao} não`}
          />
        )}
        {abstPct > 0 && (
          <div
            className="bg-text-warm/50"
            style={{ width: `${abstPct}%` }}
            aria-label={`${abst} abstenção/ausente`}
          />
        )}
      </div>

      {/* Counts */}
      <p className="mt-2 text-xs text-text-warm font-mono">
        <span className="text-cerrado font-semibold">{fmtBR(sim)} sim</span>
        <span className="mx-1.5 text-gray-300">·</span>
        <span className="text-[#C0392B] font-semibold">{fmtBR(nao)} não</span>
        {abst > 0 && (
          <>
            <span className="mx-1.5 text-gray-300">·</span>
            <span>{fmtBR(abst)} abs/aus</span>
          </>
        )}
      </p>
    </div>
  );
}

export default function FeaturedBillCard({
  bill,
  label,
  description,
  theme,
}: {
  bill: FeaturedBill;
  label: string;
  description: string;
  theme: string;
}) {
  const style = THEME_STYLE[theme] ?? {
    chipCls: "bg-text-warm text-white",
    accentCls: "group-hover:border-l-text-warm",
    label: theme,
  };

  function askFarol(e: React.MouseEvent) {
    // Don't bubble — we don't want this to also trigger a hypothetical
    // outer card-link if one is added later.
    e.stopPropagation();
    const query = `Como os deputados votaram no ${label}?`;
    window.dispatchEvent(
      new CustomEvent("farol-ask", { detail: { query } }),
    );
  }

  // We can't make the whole card a Link because it has nested buttons.
  // The "Ver votação" link is the primary CTA inside.
  const billHref = bill.id ? `/projetos/${bill.id}` : "#";

  return (
    <article
      className={`group rounded-lg border border-concreto-shadow bg-concreto p-5 flex flex-col gap-3 transition-all hover:-translate-y-0.5 hover:shadow-md border-l-[3px] border-l-transparent ${style.accentCls}`}
    >
      {/* Header chips */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span
          className={`text-xs px-2.5 py-1 rounded-full font-medium ${style.chipCls}`}
        >
          {style.label}
        </span>
        <RiskBadge score={bill.const_risk_score} />
      </div>

      {/* Label + description */}
      <div>
        <h3 className="font-display text-base font-bold text-brasilia leading-snug line-clamp-2">
          {label}
        </h3>
        <p className="text-xs text-text-warm mt-1.5 line-clamp-2 leading-relaxed">
          {description}
        </p>
      </div>

      {/* Vote bar */}
      <VoteBar bill={bill} />

      {/* CTAs */}
      <div className="flex items-center gap-2 mt-auto pt-2 border-t border-concreto-shadow">
        {bill.id ? (
          <Link
            href={billHref}
            className="text-xs text-cerrado hover:text-ochre font-semibold transition-colors"
          >
            Ver votação →
          </Link>
        ) : (
          <span className="text-xs text-text-warm italic">Sem detalhes</span>
        )}
        <span className="text-text-warm">·</span>
        <button
          onClick={askFarol}
          className="text-xs text-cerrado hover:text-ochre font-semibold transition-colors inline-flex items-center gap-1"
          aria-label={`Perguntar ao Farol sobre ${label}`}
        >
          <span>💬</span>
          <span>Farol</span>
        </button>
      </div>
    </article>
  );
}

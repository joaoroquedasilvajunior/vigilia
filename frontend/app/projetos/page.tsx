"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getBills, type Bill } from "@/lib/api";

const BILL_TYPES = ["PL", "PEC", "MPV", "PDL", "PLP"];

const THEMES = [
  { slug: "trabalho", label: "Trabalho" },
  { slug: "meio-ambiente", label: "Meio Ambiente" },
  { slug: "saude", label: "Saúde" },
  { slug: "educacao", label: "Educação" },
  { slug: "seguranca-publica", label: "Segurança Pública" },
  { slug: "agronegocio", label: "Agronegócio" },
  { slug: "tributacao", label: "Tributação" },
  { slug: "direitos-lgbtqia", label: "Direitos LGBTQIA+" },
];

const THEME_LABELS: Record<string, string> = Object.fromEntries(
  THEMES.map((t) => [t.slug, t.label]),
);

function RiskBadge({ score }: { score: number | null }) {
  if (score === null) return null;
  if (score > 0.6)
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">
        risco alto
      </span>
    );
  if (score > 0.3)
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700 font-medium">
        risco médio
      </span>
    );
  return (
    <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium">
      baixo risco
    </span>
  );
}

function BillCard({ bill }: { bill: Bill }) {
  return (
    <Link
      href={`/projetos/${bill.id}`}
      className="block rounded-lg border border-concreto-shadow bg-concreto p-4 hover:border-l-[3px] hover:border-l-ochre transition-all"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className="text-xs font-mono font-bold text-white bg-brasilia px-2 py-0.5 rounded-md">
              {bill.type} {bill.number}/{bill.year}
            </span>
            {bill.urgency_regime && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-ochre text-white font-medium">
                urgência
              </span>
            )}
            {bill.secrecy_vote && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-concreto-shadow text-text-warm">
                votação secreta
              </span>
            )}
          </div>
          <p className="text-sm text-brasilia font-medium line-clamp-2">{bill.title}</p>
          <div className="flex items-center gap-2 mt-2.5 flex-wrap">
            <span className="text-xs text-text-warm italic">
              {bill.status ?? "Em tramitação"}
            </span>
            {(bill.theme_tags ?? []).slice(0, 3).map((t) => (
              <span
                key={t}
                className="text-xs px-2 py-0.5 bg-cerrado text-white rounded-full font-medium"
              >
                {THEME_LABELS[t] ?? t}
              </span>
            ))}
          </div>
        </div>
        <div className="shrink-0">
          <RiskBadge score={bill.const_risk_score} />
        </div>
      </div>
    </Link>
  );
}

export default function ProjetosPage() {
  const [bills, setBills] = useState<Bill[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const [type, setType] = useState("");
  const [theme, setTheme] = useState("");
  const [highRisk, setHighRisk] = useState(false);

  useEffect(() => {
    setLoading(true);
    getBills({
      type: type || undefined,
      theme: theme || undefined,
      high_risk: highRisk || undefined,
      page,
      page_size: 30,
    })
      .then((res) => {
        setBills(res.items);
        setTotal(res.total);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [type, theme, highRisk, page]);

  return (
    <main className="max-w-5xl mx-auto px-4 py-10">
      <h1 className="font-display text-3xl font-bold text-brasilia mb-2">
        Projetos de Lei
      </h1>
      <p className="text-text-warm text-sm mb-6">Câmara dos Deputados — 57ª Legislatura</p>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row sm:flex-wrap gap-3 mb-6">
        <select
          value={type}
          onChange={(e) => { setType(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-full sm:w-auto"
        >
          <option value="">Todos os tipos</option>
          {BILL_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>

        <select
          value={theme}
          onChange={(e) => { setTheme(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-full sm:w-auto"
        >
          <option value="">Todos os temas</option>
          {THEMES.map((t) => <option key={t.slug} value={t.slug}>{t.label}</option>)}
        </select>

        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={highRisk}
            onChange={(e) => { setHighRisk(e.target.checked); setPage(1); }}
            className="w-4 h-4 rounded text-blue-600"
          />
          Apenas alto risco constitucional
        </label>
      </div>

      {loading ? (
        <div className="text-center py-16 text-gray-400">Carregando...</div>
      ) : (
        <>
          <p className="text-xs text-gray-400 mb-3">{total} projetos encontrados</p>
          <div className="space-y-3">
            {bills.length === 0 ? (
              <p className="text-gray-400 text-sm text-center py-12">Nenhum projeto encontrado.</p>
            ) : (
              bills.map((b) => <BillCard key={b.id} bill={b} />)
            )}
          </div>

          <div className="flex justify-between items-center mt-6 text-sm text-gray-600">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 border rounded-lg disabled:opacity-40 hover:bg-gray-50"
            >
              ← Anterior
            </button>
            <span>Página {page} de {Math.ceil(total / 30)}</span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={page * 30 >= total}
              className="px-3 py-1.5 border rounded-lg disabled:opacity-40 hover:bg-gray-50"
            >
              Próxima →
            </button>
          </div>
        </>
      )}
    </main>
  );
}

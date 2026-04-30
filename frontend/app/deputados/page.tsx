"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getLegislators, type Legislator } from "@/lib/api";

const STATES = [
  "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS",
  "MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC",
  "SP","SE","TO",
];

function AlignmentBadge({ score }: { score: number | null }) {
  if (score === null) return <span className="text-gray-400 text-xs">—</span>;
  const label = score > 0.3 ? "alto" : score < -0.3 ? "baixo" : "médio";
  const cls =
    score > 0.3
      ? "bg-emerald-100 text-emerald-800"
      : score < -0.3
      ? "bg-red-100 text-red-800"
      : "bg-yellow-100 text-yellow-800";
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cls}`}>
      {label}
    </span>
  );
}

export default function DeputadosPage() {
  const [legislators, setLegislators] = useState<Legislator[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const [state, setState] = useState("");
  const [party, setParty] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    setLoading(true);
    getLegislators({ state: state || undefined, party: party || undefined, page, page_size: 50 })
      .then((res) => {
        setLegislators(res.items);
        setTotal(res.total);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [state, party, page]);

  const filtered = search
    ? legislators.filter((l) =>
        (l.display_name ?? l.name).toLowerCase().includes(search.toLowerCase())
      )
    : legislators;

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Deputados Federais</h1>
      <p className="text-gray-500 text-sm mb-6">57ª Legislatura (2023–2027)</p>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6">
        <input
          type="search"
          placeholder="Buscar por nome..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-56 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <select
          value={state}
          onChange={(e) => { setState(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Todos os estados</option>
          {STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input
          type="text"
          placeholder="Partido (ex: PT)"
          value={party}
          onChange={(e) => { setParty(e.target.value.toUpperCase()); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-36 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-center py-16 text-gray-400">Carregando...</div>
      ) : (
        <>
          <p className="text-xs text-gray-400 mb-3">{total} deputados encontrados</p>

          {/* Desktop table — hidden on mobile */}
          <div className="hidden md:block overflow-x-auto rounded-xl border border-gray-200">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-3 text-left">Deputado</th>
                  <th className="px-4 py-3 text-left">UF</th>
                  <th className="px-4 py-3 text-left">Partido</th>
                  <th className="px-4 py-3 text-left">Alinhamento CF/88</th>
                  <th className="px-4 py-3 text-left">Ausências</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.map((l) => (
                  <tr key={l.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <Link href={`/deputados/${l.id}`} className="flex items-center gap-3 group">
                        {l.photo_url ? (
                          <img
                            src={l.photo_url}
                            alt={l.display_name ?? l.name}
                            className="w-8 h-8 rounded-full object-cover ring-1 ring-gray-200"
                          />
                        ) : (
                          <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-gray-500 text-xs font-bold">
                            {(l.display_name ?? l.name).charAt(0)}
                          </div>
                        )}
                        <span className="text-gray-900 font-medium group-hover:text-blue-600 transition-colors">
                          {l.display_name ?? l.name}
                        </span>
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-gray-500">{l.state_uf}</td>
                    <td className="px-4 py-3">
                      {l.party_acronym ? (
                        <span className="text-xs font-semibold px-2 py-0.5 rounded bg-gray-100 text-gray-700">
                          {l.party_acronym}
                        </span>
                      ) : (
                        <span className="text-gray-300 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <AlignmentBadge score={l.const_alignment_score} />
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {l.absence_rate !== null
                        ? `${(l.absence_rate * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile card list — hidden on md+ */}
          <ul className="md:hidden space-y-2">
            {filtered.map((l) => (
              <li key={l.id}>
                <Link
                  href={`/deputados/${l.id}`}
                  className="flex items-center gap-3 p-3 rounded-xl border border-gray-200 hover:border-blue-300 hover:bg-blue-50/40 transition-all group"
                >
                  {l.photo_url ? (
                    <img
                      src={l.photo_url}
                      alt={l.display_name ?? l.name}
                      className="w-10 h-10 rounded-full object-cover ring-1 ring-gray-200 shrink-0"
                    />
                  ) : (
                    <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center text-gray-500 text-sm font-bold shrink-0">
                      {(l.display_name ?? l.name).charAt(0)}
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 group-hover:text-blue-700 transition-colors truncate">
                      {l.display_name ?? l.name}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {l.party_acronym ?? "—"} · {l.state_uf}
                    </p>
                  </div>
                </Link>
              </li>
            ))}
          </ul>

          {/* Pagination */}
          <div className="flex justify-between items-center mt-4 text-sm text-gray-600">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 border rounded-lg disabled:opacity-40 hover:bg-gray-50"
            >
              ← Anterior
            </button>
            <span>Página {page} de {Math.ceil(total / 50)}</span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={page * 50 >= total}
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

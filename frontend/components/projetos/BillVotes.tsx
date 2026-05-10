"use client";

import { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import type { BillVotes } from "@/lib/api";

function fmtBR(n: number): string {
  return new Intl.NumberFormat("pt-BR").format(n);
}

function clusterChipClass(label: string | null): string {
  if (!label) return "bg-gray-300 text-brasilia";
  const l = label.toLowerCase();
  if (/coaliz[aã]o\s+govern/.test(l)) return "bg-cerrado text-white";
  if (/centr[aã]o/.test(l))           return "bg-ochre text-white";
  if (/bolsonar/.test(l))             return "bg-brasilia text-white";
  return "bg-gray-300 text-brasilia";
}

export default function BillVotesSection({ data }: { data: BillVotes }) {
  const [expanded, setExpanded] = useState(false);
  const { summary, outcome, nao_voters, status } = data;
  const { sim, "não": nao, other, total } = summary;

  if (total === 0) {
    return (
      <section>
        <h2 className="text-lg font-semibold text-gray-900 mb-3">
          Votação no plenário
        </h2>
        <div className="rounded-2xl border border-gray-200 p-5 bg-white">
          <p className="text-sm text-gray-500 italic">
            Sem votos nominais registrados para este projeto.
          </p>
        </div>
      </section>
    );
  }

  // Bar percentages — same vocabulary as FeaturedBillCard so the visual
  // reads identically across the site.
  const simPct = (sim / total) * 100;
  const naoPct = (nao / total) * 100;
  const otherPct = (other / total) * 100;
  const showCaveat = outcome === "approved" && nao > sim;

  return (
    <section>
      <h2 className="text-lg font-semibold text-gray-900 mb-3">
        Votação no plenário
      </h2>
      <div className="rounded-2xl border border-gray-200 bg-white overflow-hidden">
        <div className="p-5 space-y-4">
          {/* Outcome badge row */}
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <p className="text-[11px] font-display font-bold text-text-warm uppercase tracking-widest">
              {fmtBR(total)} votos registrados
            </p>
            {outcome === "approved" && (
              <span className="text-xs px-2.5 py-1 rounded-full bg-emerald-100 text-emerald-700 font-bold uppercase tracking-wider">
                Aprovada
              </span>
            )}
            {outcome === "rejected" && (
              <span className="text-xs px-2.5 py-1 rounded-full bg-red-100 text-red-700 font-bold uppercase tracking-wider">
                Rejeitada
              </span>
            )}
            {outcome === "pending" && status && (
              <span className="text-xs px-2.5 py-1 rounded-full bg-gray-100 text-text-warm font-medium">
                {status}
              </span>
            )}
          </div>

          {/* Stacked bar */}
          <div>
            <div className="h-3.5 bg-concreto-shadow rounded-full overflow-hidden flex">
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
              {otherPct > 0 && (
                <div
                  className="bg-text-warm/50"
                  style={{ width: `${otherPct}%` }}
                  aria-label={`${other} abstenção/ausente/obstrução`}
                />
              )}
            </div>

            <p className="mt-2.5 text-sm font-mono text-text-warm">
              <span className="text-cerrado font-semibold">{fmtBR(sim)} sim</span>
              <span className="mx-2 text-gray-300">·</span>
              <span className="text-[#C0392B] font-semibold">{fmtBR(nao)} não</span>
              {other > 0 && (
                <>
                  <span className="mx-2 text-gray-300">·</span>
                  <span>{fmtBR(other)} abs/aus</span>
                </>
              )}
              <span className="mx-2 text-gray-300">·</span>
              <span className="text-text-warm/70">
                {Math.round(simPct)}% sim
              </span>
            </p>

            {showCaveat && (
              <p className="mt-2 text-xs text-text-warm/80 italic leading-snug">
                Aprovada em votação multi-turno; placar mostra o último voto
                registrado por deputado.
              </p>
            )}
          </div>
        </div>

        {/* Disclosure: list of "não" voters */}
        {nao_voters.length > 0 && (
          <div className="border-t border-gray-200">
            <button
              type="button"
              onClick={() => setExpanded((e) => !e)}
              className="w-full flex items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-brasilia hover:bg-concreto/40 transition-colors"
              aria-expanded={expanded}
            >
              <span>
                Ver os{" "}
                <span className="font-mono text-[#C0392B]">{nao_voters.length}</span>{" "}
                deputado{nao_voters.length === 1 ? "" : "s"} que votaram NÃO
              </span>
              <span className={`transition-transform ${expanded ? "rotate-180" : ""}`}>
                ▼
              </span>
            </button>
            {expanded && (
              <ul className="border-t border-gray-200 divide-y divide-gray-100">
                {nao_voters.map((v) => (
                  <li key={v.id}>
                    <Link
                      href={`/deputados/${v.id}`}
                      className="flex items-center gap-3 px-5 py-2.5 hover:bg-concreto/40 transition-colors group"
                    >
                      {v.photo_url ? (
                        <Image
                          src={v.photo_url}
                          alt=""
                          width={32}
                          height={32}
                          className="rounded-full bg-concreto-shadow object-cover shrink-0"
                          unoptimized
                        />
                      ) : (
                        <div className="w-8 h-8 rounded-full bg-concreto-shadow flex items-center justify-center text-[11px] text-text-warm font-display shrink-0">
                          {(v.name[0] ?? "?").toUpperCase()}
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-brasilia font-medium truncate group-hover:text-cerrado">
                          {v.name}
                        </p>
                        <p className="text-[11px] text-text-warm font-mono">
                          {v.party ?? "—"} · {v.state ?? "—"}
                        </p>
                      </div>
                      {v.cluster && (
                        <span
                          className={`text-[9px] px-1.5 py-0.5 rounded-full shrink-0 ${clusterChipClass(v.cluster)}`}
                        >
                          {v.cluster}
                        </span>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

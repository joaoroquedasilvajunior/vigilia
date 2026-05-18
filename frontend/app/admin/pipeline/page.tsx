import type { Metadata } from "next";
import { getPipelineStatus, type PipelineStage } from "@/lib/api";

export const metadata: Metadata = {
  title: "Pipeline · admin",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

// Human-readable labels + descriptions per stage. Single source of truth so
// any new stage added to the orchestrator is at most a one-line entry here.
const STAGE_META: Record<string, { label: string; what: string; unit: string }> = {
  ingest_votes:          { label: "Ingerir votos novos",         what: "Detecta votações de plenário e re-sincroniza projetos",          unit: "projetos votados" },
  sync_orientations:     { label: "Orientações de partido",      what: "Atualiza orientações de bancada das sessões recentes",          unit: "sessões" },
  tag_bills:             { label: "Tagueamento temático",        what: "Classifica projetos sem theme_tags via Haiku",                 unit: "projetos taggeados" },
  score_constitutional:  { label: "Score constitucional",        what: "Avalia risco constitucional de projetos votados sem score",     unit: "projetos avaliados" },
  compute_discipline:    { label: "Disciplina partidária",       what: "Recalcula party_discipline_score e absence_rate",               unit: "deputados ativos" },
  compute_alignment:     { label: "Alinhamento com CF/88",       what: "Recalcula const_alignment_score por deputado",                  unit: "deputados ativos" },
  compute_clusters:      { label: "Clusters comportamentais",    what: "Re-roda k-means se houver >50 votos novos desde a última vez", unit: "deputados clusterizados" },
};

function fmtBR(n: number): string {
  return new Intl.NumberFormat("pt-BR").format(n);
}

function fmtRelative(iso: string | null): string {
  if (!iso) return "nunca";
  const t = new Date(iso).getTime();
  const sec = Math.floor((Date.now() - t) / 1000);
  if (sec < 60)      return "agora há pouco";
  if (sec < 3600)    return `${Math.floor(sec / 60)} min atrás`;
  if (sec < 86400)   return `${Math.floor(sec / 3600)}h atrás`;
  if (sec < 86400*7) return `${Math.floor(sec / 86400)} dias atrás`;
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

function fmtDuration(s: number | null): string {
  if (s == null) return "—";
  if (s < 60)   return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return `${m}m ${r}s`;
}

function statusBadge(status: PipelineStage["status"]) {
  if (status === "success") {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-bold uppercase tracking-wider">
        <span aria-hidden>✓</span> ok
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-bold uppercase tracking-wider">
        <span aria-hidden>!</span> falhou
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-gray-100 text-text-warm font-medium uppercase tracking-wider">
      nunca
    </span>
  );
}

export default async function PipelineStatusPage() {
  const res = await getPipelineStatus().catch(() => ({ stages: [] as PipelineStage[] }));
  const stages = res.stages;

  const lastRun = stages
    .map((s) => s.completed_at)
    .filter((x): x is string => !!x)
    .sort()
    .at(-1) ?? null;
  const anyFailed = stages.some((s) => s.status === "failed");

  return (
    <main className="max-w-5xl mx-auto px-4 py-10">
      <header className="mb-8">
        <p className="font-display text-xs uppercase tracking-widest text-ochre font-bold">
          Admin · pipeline
        </p>
        <h1 className="font-display text-3xl font-bold text-brasilia mt-2 leading-tight">
          Pipeline de dados
        </h1>
        <p className="mt-3 text-text-warm leading-relaxed max-w-2xl">
          Sete estágios sequenciais rodam todas as madrugadas (03:00 BRT)
          mantendo perfis de deputados, scores constitucionais e clusters
          comportamentais frescos em até 24 horas.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
          <span className="text-text-warm">
            Última execução:{" "}
            <strong className="text-brasilia">{fmtRelative(lastRun)}</strong>
          </span>
          {anyFailed && (
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-red-100 text-red-700 font-bold uppercase tracking-wider">
              ! algum estágio falhou
            </span>
          )}
        </div>
      </header>

      <div className="bg-white rounded-lg border border-concreto-shadow shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-concreto-shadow bg-concreto-shadow/30">
              <th className="text-left px-4 py-2.5 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
                Estágio
              </th>
              <th className="text-left px-4 py-2.5 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest hidden sm:table-cell">
                Última execução
              </th>
              <th className="text-right px-4 py-2.5 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
                Processados
              </th>
              <th className="text-left px-4 py-2.5 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
                Status
              </th>
              <th className="text-right px-4 py-2.5 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest hidden md:table-cell">
                Duração
              </th>
            </tr>
          </thead>
          <tbody>
            {stages.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-text-warm italic">
                  Pipeline ainda não foi executado.
                </td>
              </tr>
            ) : (
              stages.map((s) => {
                const meta = STAGE_META[s.stage] ?? {
                  label: s.stage,
                  what: "",
                  unit: "",
                };
                return (
                  <tr
                    key={s.stage}
                    className="border-b border-concreto-shadow last:border-b-0 align-top"
                  >
                    <td className="px-4 py-3">
                      <p className="font-display font-bold text-brasilia leading-tight">
                        {meta.label}
                      </p>
                      <p className="text-[11px] text-text-warm mt-0.5 max-w-md">
                        {meta.what}
                      </p>
                      {s.error && (
                        <p className="text-[11px] text-red-700 mt-1 font-mono break-words">
                          {s.error.slice(0, 200)}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-text-warm hidden sm:table-cell">
                      {fmtRelative(s.completed_at)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      <span className="font-semibold text-brasilia">
                        {fmtBR(s.records_processed)}
                      </span>
                      <span className="block text-[10px] text-text-warm font-sans">
                        {meta.unit}
                      </span>
                    </td>
                    <td className="px-4 py-3">{statusBadge(s.status)}</td>
                    <td className="px-4 py-3 text-right font-mono text-text-warm hidden md:table-cell">
                      {fmtDuration(s.duration_seconds)}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-6 text-xs text-text-warm/80 max-w-2xl">
        Cada estágio falha de forma isolada — uma queda da API da Câmara
        durante a ingestão não interrompe o tagueamento, o scoring
        constitucional ou os recálculos de disciplina/alinhamento.
      </p>
    </main>
  );
}

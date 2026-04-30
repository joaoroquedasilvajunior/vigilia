import Link from "next/link";
import { getStats } from "@/lib/api";

// Always render with fresh stats — the homepage is the public face
export const dynamic = "force-dynamic";

function fmtBR(n: number): string {
  return new Intl.NumberFormat("pt-BR").format(n);
}

const PILLARS = [
  {
    icon: "🗳️",
    title: "Votações reais",
    body: "Coalizões identificadas pelo voto efetivo, não por filiação partidária.",
  },
  {
    icon: "💰",
    title: "Transparência financeira",
    body: "Quem financia cada deputado, com dados oficiais do TSE 2022.",
  },
  {
    icon: "⚖️",
    title: "Risco constitucional",
    body: "Cada projeto avaliado contra a CF/88 — alto, médio ou baixo risco.",
  },
];

export default async function HomePage() {
  // Live stats; fall back gracefully if backend is briefly unavailable
  let stats = { legislators: 0, bills: 0, votes: 0, clusters: 0 };
  try {
    stats = await getStats();
  } catch {
    /* ignore */
  }

  return (
    <main>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="bg-brasilia text-white relative overflow-hidden">
        <div className="absolute inset-0 brasilia-grid pointer-events-none" />
        {/* Soft ipê-gold glow at top-right, suggesting Niemeyer's curve */}
        <div
          className="absolute -top-32 -right-32 w-96 h-96 rounded-full opacity-10 blur-3xl pointer-events-none"
          style={{ background: "radial-gradient(circle, #E8B84B 0%, transparent 70%)" }}
        />

        <div className="relative max-w-5xl mx-auto px-4 pt-20 pb-16 sm:pt-28 sm:pb-20 text-center">
          <h1 className="font-display text-4xl sm:text-5xl md:text-6xl font-bold leading-tight tracking-tight">
            Transparência no Congresso
          </h1>
          <p className="mt-6 text-base sm:text-lg text-gray-300 max-w-2xl mx-auto leading-relaxed">
            Acompanhe votações, doadores e o alinhamento constitucional dos
            deputados federais brasileiros. Dados abertos, análise independente.
          </p>

          {/* CTAs */}
          <div className="mt-10 flex justify-center gap-3 sm:gap-4 flex-wrap">
            <Link
              href="/deputados"
              className="px-6 py-3 bg-ipe text-brasilia rounded-lg font-semibold hover:brightness-105 transition-all shadow-lg shadow-black/20"
            >
              Ver deputados
            </Link>
            <Link
              href="/coalicoes"
              className="px-6 py-3 border-2 border-white/40 text-white rounded-lg font-medium hover:border-ipe hover:text-ipe transition-colors"
            >
              Mapa de coalizões
            </Link>
          </div>

          {/* Stats bar */}
          <div className="mt-14 inline-flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-sm text-gray-300">
            <span>
              <span className="font-mono text-ipe text-base font-semibold">
                {fmtBR(stats.legislators)}
              </span>{" "}
              Deputados
            </span>
            <span className="text-gray-600 hidden sm:inline">|</span>
            <span>
              <span className="font-mono text-ipe text-base font-semibold">
                {fmtBR(stats.bills)}
              </span>{" "}
              Projetos
            </span>
            <span className="text-gray-600 hidden sm:inline">|</span>
            <span>
              <span className="font-mono text-ipe text-base font-semibold">
                {fmtBR(stats.votes)}
              </span>{" "}
              Votos
            </span>
            <span className="text-gray-600 hidden sm:inline">|</span>
            <span>
              <span className="font-mono text-ipe text-base font-semibold">
                {fmtBR(stats.clusters)}
              </span>{" "}
              Coalizões
            </span>
          </div>
        </div>
      </section>

      {/* ── Como funciona ────────────────────────────────────────────────── */}
      <section className="bg-concreto-shadow">
        <div className="max-w-5xl mx-auto px-4 py-16">
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-brasilia text-center mb-2">
            Como funciona
          </h2>
          <p className="text-text-warm text-center mb-10 max-w-xl mx-auto">
            Três pilares que tornam a Vigília diferente.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {PILLARS.map((p) => (
              <div
                key={p.title}
                className="bg-concreto rounded-lg border border-concreto-shadow p-6 hover:border-l-[3px] hover:border-l-ochre transition-all"
              >
                <div className="text-3xl mb-3" aria-hidden="true">
                  {p.icon}
                </div>
                <h3 className="font-display text-lg font-bold text-brasilia mb-2">
                  {p.title}
                </h3>
                <p className="text-sm text-text-warm leading-relaxed">{p.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}

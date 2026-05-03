import Link from "next/link";
import type { Metadata } from "next";
import {
  getDisciplineAlignmentScatter,
  getStats,
  type ScatterPoint,
} from "@/lib/api";
import ScatterDisciplineAlignment from "@/components/analises/ScatterDisciplineAlignment";

export const metadata: Metadata = {
  title: "Análises",
  description:
    "Visualizações analíticas dos votos da 57ª Legislatura — disciplina " +
    "partidária, alinhamento constitucional, coalizões reais.",
};

export const dynamic = "force-dynamic";

function fmtBR(n: number): string {
  return new Intl.NumberFormat("pt-BR").format(n);
}

export default async function AnalisesPage() {
  const [scatterRes, statsRes] = await Promise.all([
    getDisciplineAlignmentScatter().catch(() => ({
      items: [] as ScatterPoint[],
      total: 0,
    })),
    getStats().catch(() => null),
  ]);

  const points = scatterRes.items;
  const totalVotes = statsRes?.votes ?? 0;

  return (
    <main className="bg-concreto">
      <div className="max-w-6xl mx-auto px-4 py-10 sm:py-14">
        {/* ── Page header ──────────────────────────────────────────── */}
        <header className="mb-8 sm:mb-10 max-w-3xl">
          <p className="font-display text-xs uppercase tracking-widest text-ochre font-bold">
            Análise · 1 de 8
          </p>
          <h1 className="font-display text-3xl sm:text-4xl font-bold text-brasilia mt-2 leading-tight">
            Disciplina vs Consciência Constitucional
          </h1>
          <p className="mt-4 text-text-warm leading-relaxed">
            Cada ponto é um deputado federal. O eixo horizontal mede o quanto
            cada parlamentar segue a orientação do seu partido. O eixo vertical
            mede se suas votações tendem a proteger ou enfraquecer a
            Constituição Federal.
          </p>
          <p className="mt-3 text-xs text-text-warm/80">
            Baseado em{" "}
            {totalVotes > 0 ? (
              <span className="font-mono">{fmtBR(totalVotes)}</span>
            ) : (
              "milhares de"
            )}{" "}
            votos nominais da 57ª Legislatura (2023–2027).{" "}
            <Link
              href="/metodologia"
              className="text-cerrado hover:text-ochre underline underline-offset-2"
            >
              Metodologia →
            </Link>
          </p>
        </header>

        {/* ── Visualization ─────────────────────────────────────────── */}
        {points.length === 0 ? (
          <div className="bg-white rounded-lg border border-concreto-shadow p-8 text-center">
            <p className="text-text-warm">
              Dados de disciplina e alinhamento ainda não foram computados.
            </p>
            <p className="text-xs text-text-warm/70 mt-2">
              Rode <code className="font-mono">/sync/discipline</code> e{" "}
              <code className="font-mono">/sync/constitutional</code> para
              popular os scores.
            </p>
          </div>
        ) : (
          <ScatterDisciplineAlignment points={points} />
        )}

        {/* ── Reading guide ──────────────────────────────────────── */}
        <section className="mt-10 bg-concreto-shadow rounded-lg p-5 sm:p-6 border border-concreto-shadow">
          <h2 className="font-display text-lg font-bold text-brasilia">
            Como ler este gráfico
          </h2>
          <ul className="mt-3 space-y-2 text-sm text-text-warm leading-relaxed list-disc pl-5">
            <li>
              <strong className="text-brasilia">Direita</strong> = vota com o
              partido na maioria das vezes;{" "}
              <strong className="text-brasilia">esquerda</strong> = vota contra
              a orientação do partido.
            </li>
            <li>
              <strong className="text-brasilia">Cima</strong> = votos tendem a
              proteger direitos previstos na CF/88;{" "}
              <strong className="text-brasilia">baixo</strong> = votos tendem a
              enfraquecê-los.
            </li>
            <li>
              O quadrante mais sensível é o{" "}
              <strong className="text-brasilia">inferior direito</strong>:
              deputados que seguem o partido mesmo quando isso significa votar
              contra a Constituição.
            </li>
            <li>
              Cores indicam o cluster de comportamento descoberto pelo
              algoritmo, não a filiação partidária formal —{" "}
              <Link
                href="/coalicoes"
                className="text-cerrado hover:text-ochre underline underline-offset-2"
              >
                veja coalizões reais
              </Link>
              .
            </li>
          </ul>
        </section>

        {/* ── Future visualizations placeholder ────────────────────── */}
        <section className="mt-12 text-center text-text-warm">
          <p className="text-sm">
            Próximas visualizações em desenvolvimento:
          </p>
          <p className="text-xs mt-2">
            doadores · ausência · coesão partidária · risco constitucional ·
            fluxo de votos · mapa de calor · timeline
          </p>
        </section>
      </div>
    </main>
  );
}

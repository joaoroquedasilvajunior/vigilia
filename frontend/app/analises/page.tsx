import Link from "next/link";
import type { Metadata } from "next";
import {
  getDisciplineAlignmentScatter,
  getDonorVoteHeatmap,
  getSimilarVoters,
  getStateProfiles,
  getStats,
  type DonorVoteHeatmap,
  type ScatterPoint,
  type SimilarVoter,
  type StateProfile,
} from "@/lib/api";
import ScatterDisciplineAlignment from "@/components/analises/ScatterDisciplineAlignment";
import DonorVoteHeatmapView from "@/components/analises/DonorVoteHeatmap";
import StateMap from "@/components/analises/StateMap";
import SimilarVotersExamples, {
  type ExampleResult,
} from "@/components/analises/SimilarVotersExamples";

// Hand-picked exemplars for the "exemplo ao vivo" section. Chosen to span
// the political spectrum (PSOL · PSB · PL) and party sizes; updating an
// entry just means swapping the UUID — names/parties/states come from the
// API. UUIDs verified against /api/v1/legislators search.
const SIMILAR_EXAMPLES = [
  {
    id: "f0a233d2-5145-4f77-9316-f938c5030cb1",
    name: "Guilherme Boulos",
    party: "PSOL",
    state: "SP",
  },
  {
    id: "ec0db6b9-feaf-406f-af52-fb083a408be8",
    name: "Tabata Amaral",
    party: "PSB",
    state: "SP",
  },
  {
    id: "2138dfb1-ea48-4471-8716-88e8e2a70546",
    name: "Nikolas Ferreira",
    party: "PL",
    state: "MG",
  },
] as const;

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
  const [scatterRes, heatmapRes, statesRes, similarResults, statsRes] =
    await Promise.all([
      getDisciplineAlignmentScatter().catch(() => ({
        items: [] as ScatterPoint[],
        total: 0,
      })),
      getDonorVoteHeatmap().catch(
        () => ({ sectors: [], themes: [], cells: [] }) as DonorVoteHeatmap,
      ),
      getStateProfiles().catch(() => ({
        items: [] as StateProfile[],
        total: 0,
      })),
      // Pull top similar voters for each example deputy in parallel. A failed
      // fetch for one deputy returns an empty match list — the component
      // hides empty examples cleanly rather than rendering a stub card.
      Promise.all(
        SIMILAR_EXAMPLES.map(async (d) => {
          const r = await getSimilarVoters(d.id).catch(
            () => ({ items: [] as SimilarVoter[] }),
          );
          return { deputy: d, matches: r.items.slice(0, 3) } as ExampleResult;
        }),
      ),
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

        {/* ── Section separator ────────────────────────────────────── */}
        <div className="mt-14 mb-10 flex items-center gap-4" aria-hidden>
          <span className="h-px flex-1 bg-ochre/40" />
          <span className="font-display text-xs uppercase tracking-widest text-ochre font-bold">
            ✦
          </span>
          <span className="h-px flex-1 bg-ochre/40" />
        </div>

        {/* ── Visualization 2: donor × theme heatmap ───────────────── */}
        <section>
          <header className="mb-6 max-w-3xl">
            <p className="font-display text-xs uppercase tracking-widest text-ochre font-bold">
              Análise · 2 de 8
            </p>
            <h2 className="font-display text-2xl sm:text-3xl font-bold text-brasilia mt-2 leading-tight">
              Financiadores e Votações
            </h2>
            <p className="mt-3 text-text-warm leading-relaxed">
              Como deputados financiados por cada setor econômico votam em
              projetos relacionados a esse setor.
            </p>
            <p className="mt-4 text-sm text-text-warm leading-relaxed bg-concreto-shadow/50 rounded-md p-3 border-l-[3px] border-l-ochre">
              Este mapa mostra, para cada cruzamento setor × tema, a proporção
              de votos &quot;sim&quot; entre os deputados que receberam doações
              corporativas daquele setor, em projetos categorizados naquele
              tema. Uma célula verde escura indica voto majoritariamente a
              favor. <strong>Não prova causalidade</strong> — mas indica
              correlação que merece atenção pública.
            </p>
          </header>

          {heatmapRes.sectors.length === 0 ? (
            <div className="bg-white rounded-lg border border-concreto-shadow p-8 text-center">
              <p className="text-text-warm">
                Mapa de doadores × temas indisponível.
              </p>
              <p className="text-xs text-text-warm/70 mt-2">
                Verifique se as tarefas de classificação de doadores e
                tagueamento de projetos foram executadas.
              </p>
            </div>
          ) : (
            <DonorVoteHeatmapView data={heatmapRes} />
          )}

          <p className="mt-4 text-[11px] text-text-warm/80 leading-relaxed max-w-3xl">
            Dados de financiamento referentes às eleições de 2022 (TSE).
            Apenas doações de pessoas jurídicas classificadas por setor —
            número limitado de doadores corporativos devido à legislação
            pós-2015 que vetou doações de empresas a campanhas. Cada célula
            exige no mínimo 10 votos para ser exibida.
          </p>
        </section>

        {/* ── Section separator ────────────────────────────────────── */}
        <div className="mt-14 mb-10 flex items-center gap-4" aria-hidden>
          <span className="h-px flex-1 bg-ochre/40" />
          <span className="font-display text-xs uppercase tracking-widest text-ochre font-bold">
            ✦
          </span>
          <span className="h-px flex-1 bg-ochre/40" />
        </div>

        {/* ── Visualization 3: lives on deputy profiles, teaser here ─ */}
        <section>
          <header className="mb-6 max-w-3xl">
            <p className="font-display text-xs uppercase tracking-widest text-ochre font-bold">
              Análise · 3 de 8
            </p>
            <h2 className="font-display text-2xl sm:text-3xl font-bold text-brasilia mt-2 leading-tight">
              Quem vota com quem
            </h2>
            <p className="mt-3 text-text-warm leading-relaxed">
              Para cada deputado, identificamos os 10 parlamentares de outros
              partidos com padrão de voto mais parecido — revelando coalizões
              reais que cruzam fronteiras partidárias.
            </p>
          </header>

          <p className="-mt-2 mb-5 text-[10px] font-display font-bold text-text-warm uppercase tracking-widest">
            Exemplo ao vivo
          </p>
          <SimilarVotersExamples examples={similarResults} />
        </section>

        {/* ── Section separator ────────────────────────────────────── */}
        <div className="mt-14 mb-10 flex items-center gap-4" aria-hidden>
          <span className="h-px flex-1 bg-ochre/40" />
          <span className="font-display text-xs uppercase tracking-widest text-ochre font-bold">
            ✦
          </span>
          <span className="h-px flex-1 bg-ochre/40" />
        </div>

        {/* ── Visualization 4: Brazil tile-grid map ────────────────── */}
        <section>
          <header className="mb-6 max-w-3xl">
            <p className="font-display text-xs uppercase tracking-widest text-ochre font-bold">
              Análise · 4 de 8
            </p>
            <h2 className="font-display text-2xl sm:text-3xl font-bold text-brasilia mt-2 leading-tight">
              Como seu estado vota
            </h2>
            <p className="mt-3 text-text-warm leading-relaxed">
              Distribuição das coalizões comportamentais por estado — baseada
              em votações reais, não em filiação partidária. Cada quadrado é
              uma unidade federativa, colorido pela coalizão dominante.
            </p>
          </header>

          {statesRes.items.length === 0 ? (
            <div className="bg-white rounded-lg border border-concreto-shadow p-8 text-center">
              <p className="text-text-warm">
                Dados por estado indisponíveis no momento.
              </p>
            </div>
          ) : (
            <StateMap profiles={statesRes.items} />
          )}

          <p className="mt-4 text-[11px] text-text-warm/80 leading-relaxed max-w-3xl">
            Mapa em formato de grade (cada UF tem o mesmo peso visual,
            independentemente da área geográfica). Estado com cluster
            &quot;Misto&quot; significa que nenhuma coalizão concentra 40% ou
            mais da delegação. Médias calculadas sobre os deputados com score
            disponível.
          </p>
        </section>

        {/* ── Future visualizations placeholder ────────────────────── */}
        <section className="mt-14 text-center text-text-warm">
          <p className="text-sm">
            Próximas visualizações em desenvolvimento:
          </p>
          <p className="text-xs mt-2">
            ausência · coesão partidária · risco constitucional · timeline
          </p>
        </section>
      </div>
    </main>
  );
}

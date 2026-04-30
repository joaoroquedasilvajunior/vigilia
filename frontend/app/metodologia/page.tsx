import type { Metadata } from "next";
import Link from "next/link";
import { getStats } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Metodologia",
  description:
    "Como a Vigília coleta, processa e analisa dados públicos do " +
    "Congresso Nacional, do TSE e da Constituição Federal.",
};

function fmtBR(n: number): string {
  return new Intl.NumberFormat("pt-BR").format(n);
}

function Section({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-12">
      <h2 className="font-display text-2xl font-bold text-brasilia mb-4 flex items-baseline gap-3">
        <span className="font-mono text-base text-ochre">{String(n).padStart(2, "0")}</span>
        <span>{title}</span>
      </h2>
      <div className="prose prose-sm max-w-none text-brasilia [&_p]:text-brasilia [&_li]:text-brasilia [&_strong]:text-brasilia">
        {children}
      </div>
    </section>
  );
}

function Limit({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-3 pl-3 border-l-2 border-ochre/60 text-text-warm text-sm italic">
      <span className="font-semibold text-ochre not-italic">Limitação. </span>
      {children}
    </p>
  );
}

export default async function MetodologiaPage() {
  // Live counts so the page never claims stale numbers
  let stats = { legislators: 0, bills: 0, votes: 0, clusters: 0 };
  try {
    stats = await getStats();
  } catch {
    /* ignore */
  }

  // Bills with at least one vote (clustering signal) — fetched separately
  // so the methodology numbers stay honest.
  // For now we surface the platform totals; the sub-count is documented
  // qualitatively as "centenas de projetos com votação plenária".

  return (
    <main className="max-w-3xl mx-auto px-4 py-10">
      <Link
        href="/"
        className="text-sm text-cerrado hover:text-ochre transition-colors mb-6 inline-block"
      >
        ← Voltar
      </Link>

      <h1 className="font-display text-4xl font-bold text-brasilia mb-3">
        Metodologia
      </h1>
      <p className="text-text-warm leading-relaxed mb-10">
        Como a Vigília coleta, processa e analisa dados do Congresso Nacional.
        Tudo aqui é público, reproduzível e baseado em fontes oficiais. Onde a
        análise tem limites, esses limites estão escritos abaixo.
      </p>

      <Section n={1} title="Fontes de dados">
        <ul>
          <li>
            <strong>Câmara dos Deputados</strong> — API{" "}
            <a
              className="font-mono text-cerrado hover:text-ochre underline"
              href="https://dadosabertos.camara.leg.br/api/v2"
              target="_blank"
              rel="noopener noreferrer"
            >
              dadosabertos.camara.leg.br/api/v2
            </a>
            . Dados: perfis de deputados, projetos de lei, votações nominais e
            orientações de bancada. Cobertura: 57ª Legislatura (2023–2027), com
            atualização diária.
          </li>
          <li>
            <strong>Tribunal Superior Eleitoral (TSE)</strong> — portal{" "}
            <a
              className="font-mono text-cerrado hover:text-ochre underline"
              href="https://dadosabertos.tse.jus.br"
              target="_blank"
              rel="noopener noreferrer"
            >
              dadosabertos.tse.jus.br
            </a>
            . Dados: prestações de contas eleitorais de 2022. Cobertura: todos
            os candidatos a Deputado Federal, declaração oficial.
          </li>
          <li>
            <strong>Constituição Federal de 1988</strong> — texto integral
            consultado via Planalto, usado como referência para a análise de
            risco constitucional.
          </li>
        </ul>
      </Section>

      <Section n={2} title="Coalizões comportamentais">
        <p>
          Os deputados são agrupados pelo <strong>comportamento real de voto</strong>
          , não pela filiação partidária. Em outras palavras: dois deputados de
          partidos diferentes que votam de forma parecida nas mesmas matérias
          aparecem na mesma coalizão.
        </p>
        <ul>
          <li>
            Algoritmo: <span className="font-mono">k-means</span> sobre uma
            matriz <em>deputados × projetos</em>, com valores 1 (sim), −1 (não)
            e 0 (ausente ou abstenção). O número ótimo de clusters{" "}
            <span className="font-mono">k</span> é escolhido pelo melhor
            silhouette score.
          </li>
          <li>
            Cobertura atual: {fmtBR(stats.legislators)} deputados em{" "}
            {fmtBR(stats.clusters)} coalizões, calculadas a partir dos projetos
            com votação plenária registrada.
          </li>
          <li>
            Os rótulos das coalizões (ex.: <em>Bloco Bolsonarista</em>,{" "}
            <em>Coalização Governista</em>) são gerados por IA com base nos
            partidos predominantes e nas fontes de financiamento — não são
            categorias políticas oficiais.
          </li>
          <li>
            As coalizões são recalculadas a cada nova rodada de votos, à medida
            que a Câmara registra novas votações.
          </li>
        </ul>
        <Limit>
          Com poucos projetos votados, as coalizões são menos precisas. Se o
          deputado tiver votado em apenas 3 ou 4 matérias, sua atribuição a um
          cluster carrega ruído. A análise melhora à medida que mais votos são
          registrados.
        </Limit>
      </Section>

      <Section n={3} title="Risco constitucional">
        <p>
          Cada projeto submetido a votação é analisado contra a CF/88 por meio
          de um modelo de linguagem (Anthropic Claude Haiku), que retorna um
          score entre 0 e 1 representando a probabilidade de conflito
          constitucional. Quando o score passa de 0,6, classificamos como{" "}
          <strong>alto risco</strong>.
        </p>
        <ul>
          <li>
            A análise é baseada na ementa oficial e no texto do projeto, com
            referência a artigos específicos da CF/88.
          </li>
          <li>
            Cobertura atual: todos os projetos com votação plenária registrada
            no banco da Vigília.
          </li>
        </ul>
        <Limit>
          A análise por IA <strong>não é parecer jurídico</strong>. É um sinal
          computacional, não uma determinação judicial. Sinalizações de alto
          risco devem ser verificadas por profissionais do Direito antes de
          serem citadas em contextos formais. Está prevista a inclusão de uma
          camada de revisão por especialistas.
        </Limit>
      </Section>

      <Section n={4} title="Disciplina partidária">
        <p>
          Para cada deputado, calculamos a fração de votos alinhados à
          orientação oficial do seu partido nos casos em que a orientação foi
          declarada explicitamente.
        </p>
        <ul>
          <li>
            Score = votos alinhados ÷ votos com orientação declarada.
          </li>
          <li>
            Sessões marcadas como <em>livre</em> (sem orientação) são
            excluídas. Obstruções também são excluídas para não contaminar o
            score.
          </li>
          <li>
            Fonte: endpoint <span className="font-mono">/votacoes/{`{id}`}/orientacoes</span>{" "}
            da Câmara, agregado por bloco/partido.
          </li>
        </ul>
        <Limit>
          Cobre apenas votos onde houve orientação. Em sessões sem orientação
          partidária declarada, o deputado não contribui para o cálculo. A
          coesão dos blocos parlamentares (que reúnem múltiplos partidos) é
          atribuída a cada partido componente — pode haver ruído quando
          deputados trocam de partido durante o mandato.
        </Limit>
      </Section>

      <Section n={5} title="Alinhamento constitucional por deputado">
        <p>
          Métrica derivada que cruza o <em>risco constitucional</em> dos
          projetos com o voto efetivo de cada deputado. Para cada par
          (deputado, projeto):
        </p>
        <ul>
          <li>
            Peso ={" "}
            <span className="font-mono">|risk_score − 0.5| × 2</span>{" "}
            (zero no meio, máximo nos extremos).
          </li>
          <li>
            Risco &gt; 0,6 + voto &quot;não&quot; → <strong>+peso</strong>{" "}
            (oposição correta a projeto arriscado).
          </li>
          <li>
            Risco &gt; 0,6 + voto &quot;sim&quot; → <strong>−peso</strong>.
          </li>
          <li>
            Risco &lt; 0,4 + voto &quot;sim&quot; →{" "}
            <strong>+peso × 0,5</strong>.
          </li>
          <li>
            Risco &lt; 0,4 + voto &quot;não&quot; →{" "}
            <strong>−peso × 0,5</strong>.
          </li>
          <li>
            Por deputado: soma dos pesos com sinal ÷ soma dos pesos absolutos
            (resultado entre −1 e 1).
          </li>
        </ul>
        <Limit>
          A métrica é <strong>direcional, não absoluta</strong>. Mede tendência
          de voto contra projetos sinalizados como arriscados pela IA. Não
          equivale a expertise jurídica, e o sinal herda as limitações do
          score constitucional descrito acima.
        </Limit>
      </Section>

      <Section n={6} title="Financiamento eleitoral">
        <p>
          A Vigília importa as declarações oficiais de prestação de contas das
          eleições de 2022, do TSE, e cruza com a tabela de deputados pelo
          hash do CPF.
        </p>
        <ul>
          <li>
            CPF/CNPJ de doadores e candidatos são armazenados como{" "}
            <span className="font-mono">SHA-256</span> — nunca em texto claro,
            em conformidade com a LGPD.
          </li>
          <li>
            Doadores são classificados em setores econômicos a partir do
            código CNAE quando disponível, ou por correspondência textual.
          </li>
          <li>
            Pós-2015, a maior parte do financiamento vem do FEFC (Fundo
            Especial de Financiamento de Campanha). A plataforma diferencia
            essas transferências partidárias das doações diretas de pessoas
            físicas e empresas.
          </li>
        </ul>
        <Limit>
          Cobre apenas o ciclo eleitoral de 2022. Doações entre eleições e
          anos anteriores ainda não foram incorporadas. A classificação setorial
          depende da qualidade do dado de origem do TSE.
        </Limit>
      </Section>

      <Section n={7} title="Código aberto">
        <p>
          Todo o código da Vigília é aberto e auditável. O pipeline de
          ingestão, os modelos de dados, as análises e o frontend estão
          publicados no GitHub.
        </p>
        <ul>
          <li>
            Repositório:{" "}
            <a
              className="font-mono text-cerrado hover:text-ochre underline"
              href="https://github.com/joaoroquedasilvajunior/vigilia"
              target="_blank"
              rel="noopener noreferrer"
            >
              github.com/joaoroquedasilvajunior/vigilia
            </a>
          </li>
          <li>
            Sincronização diária dos dados da Câmara via GitHub Actions.
          </li>
          <li>
            Dúvidas metodológicas: abra uma <em>issue</em> no GitHub.
            Pull requests são bem-vindos.
          </li>
        </ul>
      </Section>

      <Section n={8} title="Sobre o projeto">
        <p>
          Vigília é um projeto independente de tecnologia cívica. Construído
          inteiramente sobre dados públicos disponibilizados pelas leis
          brasileiras de transparência (Lei de Acesso à Informação, Lei de
          Dados Abertos), <strong>não é afiliado a nenhum partido político
          ou órgão de governo</strong>.
        </p>
        <p>
          O assistente Farol usa a API da Anthropic (Claude) para classificar
          consultas, redigir respostas em linguagem natural e gerar análises
          temáticas. Toda resposta do Farol é fundamentada nos dados que estão
          neste banco — e quando o dado não existe, o assistente diz isso.
        </p>
      </Section>
    </main>
  );
}

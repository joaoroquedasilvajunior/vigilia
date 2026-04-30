import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getBill } from "@/lib/api";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  try {
    const bill = await getBill(id);
    const head = `${bill.type ?? "PL"} ${bill.number}/${bill.year}`;
    const baseDesc = (bill.title ?? "").slice(0, 155);
    const riskPrefix =
      bill.const_risk_score !== null && bill.const_risk_score > 0.6
        ? "⚠️ Alto risco constitucional. "
        : "";
    return {
      title: head,
      description: riskPrefix + baseDesc,
      openGraph: {
        type: "article",
        title: `${head} — Vigília`,
        description: riskPrefix + baseDesc,
        images: [{ url: "/og-default.png", width: 1200, height: 630 }],
      },
      twitter: {
        card: "summary_large_image",
        title: `${head} — Vigília`,
        description: riskPrefix + baseDesc,
        images: ["/og-default.png"],
      },
    };
  } catch {
    return { title: "Projeto de lei" };
  }
}

const THEME_LABELS: Record<string, string> = {
  trabalho: "Trabalho",
  "meio-ambiente": "Meio Ambiente",
  saude: "Saúde",
  educacao: "Educação",
  "seguranca-publica": "Segurança Pública",
  agronegocio: "Agronegócio",
  tributacao: "Tributação",
  "direitos-lgbtqia": "Direitos LGBTQIA+",
  armas: "Armas",
  religiao: "Religião",
  indigenas: "Indígenas",
  midia: "Mídia",
  "reforma-politica": "Reforma Política",
};

function RiskBadge({ score }: { score: number | null }) {
  if (score === null) return null;
  const cls =
    score > 0.6
      ? "bg-red-100 text-red-700"
      : score > 0.3
      ? "bg-yellow-100 text-yellow-700"
      : "bg-emerald-100 text-emerald-700";
  const label =
    score > 0.6 ? "alto risco" : score > 0.3 ? "risco médio" : "baixo risco";
  return (
    <span
      className={`text-xs px-2.5 py-1 rounded-full font-medium ${cls}`}
    >
      {label} · {score.toFixed(2)}
    </span>
  );
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status)
    return (
      <span className="text-xs px-2.5 py-1 rounded-full bg-gray-100 text-gray-600 font-medium">
        Em tramitação
      </span>
    );
  const lower = status.toLowerCase();
  let cls = "bg-blue-100 text-blue-700";
  if (lower.includes("arquiv")) cls = "bg-gray-200 text-gray-700";
  else if (lower.includes("transformad") || lower.includes("aprovad"))
    cls = "bg-emerald-100 text-emerald-700";
  else if (lower.includes("rejeitad")) cls = "bg-red-100 text-red-700";
  return (
    <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${cls}`}>
      {status}
    </span>
  );
}

function ThemeChip({ slug }: { slug: string }) {
  const label = THEME_LABELS[slug] ?? slug;
  return (
    <span className="text-xs px-2.5 py-1 rounded-full bg-purple-50 text-purple-700 font-medium border border-purple-100">
      {label}
    </span>
  );
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "long",
      year: "numeric",
    });
  } catch {
    return value;
  }
}

export default async function BillDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let bill;
  try {
    bill = await getBill(id);
  } catch {
    notFound();
  }

  const summary = bill.summary_official ?? bill.summary_ai ?? null;

  return (
    <main className="max-w-4xl mx-auto px-4 py-8">
      <Link
        href="/projetos"
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        ← Todos os projetos
      </Link>

      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <span className="text-sm font-bold text-blue-700 bg-blue-50 px-3 py-1 rounded-lg">
            {bill.type} {bill.number}/{bill.year}
          </span>
          <StatusBadge status={bill.status} />
          {bill.urgency_regime && (
            <span className="text-xs px-2.5 py-1 rounded-full bg-orange-50 text-orange-700 font-medium border border-orange-100">
              urgência
            </span>
          )}
          {bill.secrecy_vote && (
            <span className="text-xs px-2.5 py-1 rounded-full bg-gray-100 text-gray-600 font-medium">
              votação secreta
            </span>
          )}
          <RiskBadge score={bill.const_risk_score} />
        </div>

        <h1 className="text-2xl font-bold text-gray-900 leading-snug">
          {bill.title}
        </h1>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        {/* Metadata card */}
        <div className="rounded-2xl border border-gray-200 p-5">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Apresentação
          </h2>
          <p className="text-sm text-gray-900">
            {formatDate(bill.presentation_date)}
          </p>
        </div>

        {/* Theme card */}
        <div className="rounded-2xl border border-gray-200 p-5 md:col-span-2">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Temas
          </h2>
          {bill.theme_tags && bill.theme_tags.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {bill.theme_tags.map((slug) => (
                <ThemeChip key={slug} slug={slug} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400">
              Ainda não classificado
            </p>
          )}
        </div>
      </div>

      {/* Summary */}
      {summary && (
        <section className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Ementa</h2>
          <div className="rounded-2xl border border-gray-200 p-5 bg-white">
            <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-line">
              {summary}
            </p>
          </div>
        </section>
      )}

      {/* Affected articles */}
      {bill.affected_articles && bill.affected_articles.length > 0 && (
        <section className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">
            Artigos da CF/88 afetados
          </h2>
          <div className="rounded-2xl border border-gray-200 p-5 bg-white">
            <div className="flex flex-wrap gap-2">
              {bill.affected_articles.map((art) => (
                <span
                  key={art}
                  className="text-xs px-2.5 py-1 rounded bg-amber-50 text-amber-800 font-mono"
                >
                  {art}
                </span>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* External link */}
      {bill.full_text_url && (
        <section className="mb-8">
          <a
            href={bill.full_text_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-blue-600 hover:underline"
          >
            Texto completo na Câmara dos Deputados →
          </a>
        </section>
      )}
    </main>
  );
}

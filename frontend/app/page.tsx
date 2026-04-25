import Link from "next/link";

export default function HomePage() {
  return (
    <main className="max-w-4xl mx-auto px-4 py-20 text-center">
      <h1 className="text-4xl font-bold text-gray-900 mb-4">
        Transparência no Congresso
      </h1>
      <p className="text-lg text-gray-500 mb-10 max-w-xl mx-auto">
        Acompanhe votações, doadores e o alinhamento constitucional dos deputados federais.
        Dados abertos, análise independente.
      </p>
      <div className="flex justify-center gap-4 flex-wrap">
        <Link
          href="/deputados"
          className="px-6 py-3 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 transition-colors"
        >
          Ver deputados
        </Link>
        <Link
          href="/projetos"
          className="px-6 py-3 border border-gray-300 text-gray-700 rounded-xl font-medium hover:bg-gray-50 transition-colors"
        >
          Projetos de lei
        </Link>
      </div>
    </main>
  );
}

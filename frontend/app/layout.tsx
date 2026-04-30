import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Playfair_Display } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import FarolWidget from "@/components/farol/FarolWidget";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});
const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
  weight: ["400", "700"],
  display: "swap",
});
const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

const SITE_URL = "https://plataforma-vigilia.vercel.app";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Vigília — Transparência no Congresso Nacional",
    template: "%s · Vigília",
  },
  description:
    "Acompanhe votações, doadores e o alinhamento constitucional dos " +
    "deputados federais brasileiros. Dados abertos, análise independente.",
  alternates: { canonical: SITE_URL },
  robots: { index: true, follow: true },
  openGraph: {
    type: "website",
    siteName: "Vigília",
    url: SITE_URL,
    title: "Vigília — Transparência no Congresso Nacional",
    description:
      "Acompanhe votações, doadores e o alinhamento constitucional dos " +
      "deputados federais brasileiros.",
    locale: "pt_BR",
    images: [{ url: "/og-default.png", width: 1200, height: 630, alt: "Vigília" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Vigília — Transparência no Congresso Nacional",
    description:
      "Acompanhe votações, doadores e o alinhamento constitucional dos " +
      "deputados federais brasileiros.",
    images: ["/og-default.png"],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="pt-BR"
      className={`${inter.variable} ${playfair.variable} ${jetbrains.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-concreto text-brasilia">
        {/* ── Nav ──────────────────────────────────────────────────────── */}
        <nav className="bg-brasilia border-b-2 border-ochre/80 sticky top-0 z-40">
          <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
            <Link
              href="/"
              className="font-display font-bold text-xl tracking-tight text-white"
            >
              Vigília
            </Link>
            <div className="flex items-center gap-5 sm:gap-7 text-sm text-gray-300">
              <Link href="/deputados" className="hover:text-ipe transition-colors">
                Deputados
              </Link>
              <Link href="/projetos" className="hover:text-ipe transition-colors">
                Projetos
              </Link>
              <Link href="/coalicoes" className="hover:text-ipe transition-colors">
                Coalizões
              </Link>
            </div>
          </div>
        </nav>

        <div className="flex-1">{children}</div>

        {/* ── Footer ───────────────────────────────────────────────────── */}
        <footer className="bg-brasilia text-gray-300 mt-16">
          <div className="max-w-6xl mx-auto px-4 py-10 flex flex-col sm:flex-row gap-6 items-start sm:items-center justify-between">
            <div>
              <p className="font-display text-lg text-white">Vigília</p>
              <p className="text-sm text-gray-400 mt-1">
                Dados abertos, análise independente.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-6 text-sm">
              <a
                href="https://github.com/joaoroquedasilvajunior/vigilia"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-ipe transition-colors"
              >
                GitHub
              </a>
              <Link href="/coalicoes" className="hover:text-ipe transition-colors">
                Metodologia
              </Link>
              <a
                href="https://dadosabertos.camara.leg.br"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-ipe transition-colors"
              >
                Câmara dos Deputados
              </a>
            </div>
          </div>
        </footer>

        <FarolWidget />
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import { Geist } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import FarolWidget from "@/components/farol/FarolWidget";

const geist = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

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
    <html lang="pt-BR" className={`${geist.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-white text-gray-900">
        <nav className="border-b border-gray-100 sticky top-0 bg-white/95 backdrop-blur z-40">
          <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
            <Link href="/" className="font-bold text-lg tracking-tight text-gray-900">
              Vigília
            </Link>
            <div className="flex items-center gap-6 text-sm text-gray-600">
              <Link href="/deputados" className="hover:text-gray-900 transition-colors">
                Deputados
              </Link>
              <Link href="/projetos" className="hover:text-gray-900 transition-colors">
                Projetos
              </Link>
              <Link href="/coalicoes" className="hover:text-gray-900 transition-colors">
                Coalizões
              </Link>
            </div>
          </div>
        </nav>
        <div className="flex-1">{children}</div>
        <FarolWidget />
      </body>
    </html>
  );
}

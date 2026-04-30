import type { Metadata } from "next";
import { Geist } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import FarolWidget from "@/components/farol/FarolWidget";

const geist = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Vigília — Monitoramento Legislativo",
  description: "Transparência no Congresso Nacional brasileiro",
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

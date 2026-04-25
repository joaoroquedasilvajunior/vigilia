"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

// ── Types ──────────────────────────────────────────────────────────────────────

type Source =
  | { type: "legislator"; id: string; name: string }
  | { type: "bill"; id: string; label: string }
  | { type: "vote"; bill_label: string; vote_value: string };

interface AssistantMessage {
  role: "assistant";
  content: string;
  sources: Source[];
}

interface UserMessage {
  role: "user";
  content: string;
}

type Message = UserMessage | AssistantMessage;

// ── Constants ──────────────────────────────────────────────────────────────────

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const SESSION_KEY = "farol_session_id";

const WELCOME: AssistantMessage = {
  role: "assistant",
  content:
    "Olá! Sou o Farol, o assistente de transparência da Vigília. Posso te ajudar a entender votações, perfis de deputados, projetos de lei e financiamento eleitoral. O que você quer saber?",
  sources: [],
};

// ── Sub-components ─────────────────────────────────────────────────────────────

function SourceBadge({ source, onClick }: { source: Source; onClick?: () => void }) {
  const base =
    "inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border transition-colors cursor-pointer select-none";

  if (source.type === "legislator") {
    return (
      <button
        onClick={onClick}
        className={`${base} bg-blue-50 border-blue-200 text-blue-700 hover:bg-blue-100`}
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
        {source.name}
      </button>
    );
  }

  if (source.type === "bill") {
    return (
      <button
        onClick={onClick}
        className={`${base} bg-emerald-50 border-emerald-200 text-emerald-700 hover:bg-emerald-100`}
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        {source.label}
      </button>
    );
  }

  // vote — not clickable, just a label
  const voteColor =
    source.vote_value === "sim"
      ? "bg-green-50 border-green-200 text-green-700"
      : source.vote_value === "não"
      ? "bg-red-50 border-red-200 text-red-700"
      : "bg-gray-50 border-gray-200 text-gray-600";
  return (
    <span className={`${base} ${voteColor}`}>
      {source.bill_label} → {source.vote_value}
    </span>
  );
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="bg-gray-100 rounded-2xl rounded-bl-sm px-3 py-2.5">
        <span className="flex gap-1 items-center">
          {[0, 150, 300].map((delay) => (
            <span
              key={delay}
              className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce"
              style={{ animationDelay: `${delay}ms` }}
            />
          ))}
        </span>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function FarolWidget() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Restore session from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(SESSION_KEY);
    if (stored) setSessionId(stored);
  }, []);

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, open, loading]);

  // Focus input when widget opens
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: UserMessage = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/farol/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data: { response: string; sources: Source[]; session_id: string } = await res.json();

      // Persist session id for follow-ups across page navigation
      if (data.session_id && data.session_id !== sessionId) {
        setSessionId(data.session_id);
        localStorage.setItem(SESSION_KEY, data.session_id);
      }

      const assistantMsg: AssistantMessage = {
        role: "assistant",
        content: data.response,
        sources: data.sources ?? [],
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Desculpe, não consegui processar sua pergunta agora. Tente novamente em instantes.",
          sources: [],
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleSourceClick(source: Source) {
    if (source.type === "legislator") {
      router.push(`/deputados/${source.id}`);
      setOpen(false);
    } else if (source.type === "bill") {
      router.push(`/projetos/${source.id}`);
      setOpen(false);
    }
  }

  // Deduplicate sources shown per message
  function dedupeSources(sources: Source[]): Source[] {
    const seen = new Set<string>();
    return sources.filter((s) => {
      const key = s.type === "vote" ? `vote:${s.bill_label}` : `${s.type}:${(s as { id?: string }).id}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  return (
    <>
      {/* Floating toggle button */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-blue-600 text-white shadow-lg hover:bg-blue-700 active:scale-95 transition-all flex items-center justify-center"
        aria-label={open ? "Fechar Farol" : "Abrir Farol"}
      >
        {open ? (
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        ) : (
          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
        )}
      </button>

      {/* Chat panel */}
      {open && (
        <div className="fixed bottom-24 right-6 z-50 w-96 max-w-[calc(100vw-3rem)] bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col overflow-hidden"
          style={{ maxHeight: "min(600px, calc(100dvh - 8rem))" }}
        >
          {/* Header */}
          <div className="bg-blue-600 text-white px-4 py-3 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center text-sm font-bold">
                F
              </div>
              <div>
                <p className="text-sm font-semibold leading-tight">Farol</p>
                <p className="text-xs text-blue-200 leading-tight">Assistente de transparência</p>
              </div>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-blue-200 hover:text-white transition-colors p-1"
              aria-label="Fechar"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
            {messages.map((msg, i) => (
              <div key={i} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-blue-600 text-white rounded-br-sm"
                      : "bg-gray-100 text-gray-900 rounded-bl-sm"
                  }`}
                >
                  {msg.content}
                </div>

                {/* Sources */}
                {msg.role === "assistant" && msg.sources.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5 max-w-[90%]">
                    {dedupeSources(msg.sources).map((source, j) => (
                      <SourceBadge
                        key={j}
                        source={source}
                        onClick={
                          source.type !== "vote"
                            ? () => handleSourceClick(source)
                            : undefined
                        }
                      />
                    ))}
                  </div>
                )}
              </div>
            ))}
            {loading && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="border-t border-gray-100 p-3 flex gap-2 shrink-0">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Pergunte sobre deputados, projetos..."
              className="flex-1 text-sm border border-gray-200 rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              disabled={loading}
              maxLength={400}
            />
            <button
              onClick={send}
              disabled={loading || !input.trim()}
              className="px-3 py-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-40 transition-colors active:scale-95"
              aria-label="Enviar"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </>
  );
}

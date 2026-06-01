import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

interface Msg {
  role: "user" | "assistant";
  content: string;
  route?: string;
  used_tools?: string[];
}

const SUGGESTIONS = [
  "How much did I spend on groceries last month?",
  "What was my biggest purchase in March?",
  "Show my recurring subscriptions",
  "Anything unusual recently?",
  "Am I spending more than usual this month?",
  "How am I doing against my budget?",
  "What is the SQH*UNKNOWN-MERCHANT charge?",
  "Summarise my finances",
  "Where can I cut back?",
  "Remember that I get paid on the 1st",
];

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export default function Chat() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .get<Msg[]>("/api/chat/history")
      .then(setMessages)
      .catch(() => {});
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string) {
    if ((!text.trim() && !image) || busy) return;
    const userMsg: Msg = { role: "user", content: text || "(receipt image)" };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setBusy(true);
    const img = image;
    setImage(null);
    try {
      const res = await api.post<{
        answer: string;
        route: string;
        used_tools: string[];
      }>("/api/chat", {
        message: text,
        image_base64: img,
      });
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: res.answer,
          route: res.route,
          used_tools: res.used_tools,
        },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `Error: ${(e as Error).message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    send(input);
  }

  async function onPickImage(file: File) {
    const dataUrl = await fileToDataUrl(file);
    setImage(dataUrl);
  }

  return (
    <div className="flex h-screen flex-col">
      <div className="border-b border-slate-200 bg-white px-8 py-4">
        <h1 className="text-lg font-semibold text-slate-800">Assistant</h1>
        <p className="text-xs text-slate-400">
          Ask about your money in plain language, or upload a receipt photo.
        </p>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-8 py-6">
        {messages.length === 0 && (
          <div className="mx-auto max-w-2xl">
            <p className="mb-3 text-sm text-slate-400">Try asking:</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 hover:border-brand-300 hover:bg-brand-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-2xl rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
                m.role === "user"
                  ? "bg-brand-600 text-white"
                  : "border border-slate-200 bg-white text-slate-700"
              }`}
            >
              {m.content}
              {m.role === "assistant" && m.route && (
                <div className="mt-2 flex flex-wrap gap-1">
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
                    {m.route}
                  </span>
                  {m.used_tools?.map((t) => (
                    <span
                      key={t}
                      className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-400"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex justify-start">
            <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-400">
              Thinking…
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={onSubmit} className="border-t border-slate-200 bg-white p-4">
        {image && (
          <div className="mb-2 flex items-center gap-2">
            <img src={image} alt="receipt" className="h-12 w-12 rounded object-cover" />
            <button
              type="button"
              onClick={() => setImage(null)}
              className="text-xs text-slate-400 hover:text-slate-600"
            >
              remove
            </button>
          </div>
        )}
        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && onPickImage(e.target.files[0])}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-500 hover:bg-slate-50"
            title="Attach receipt"
          >
            📎
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about your finances…"
            className="flex-1 rounded-lg border border-slate-200 px-4 py-2 text-sm focus:border-brand-500 focus:outline-none"
          />
          <button
            disabled={busy}
            className="rounded-lg bg-brand-600 px-5 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}

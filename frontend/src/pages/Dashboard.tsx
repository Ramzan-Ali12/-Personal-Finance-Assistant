import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { money, shortDate } from "../lib/format";

interface BudgetStatus {
  id: number;
  category: string;
  period: string;
  limit: number;
  spent: number;
  remaining: number;
  pct_used: number;
  status: "ok" | "warning" | "over";
}
interface Txn {
  id: number;
  txn_date: string;
  amount: number;
  merchant: string;
  category: string;
  currency: string;
}
interface Health {
  llm_mode: string;
  web_search: string;
}

export default function Dashboard() {
  const [budgets, setBudgets] = useState<BudgetStatus[]>([]);
  const [recent, setRecent] = useState<Txn[]>([]);
  const [count, setCount] = useState(0);
  const [health, setHealth] = useState<Health | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function load() {
    const [b, t, h] = await Promise.all([
      api.get<BudgetStatus[]>("/api/budgets"),
      api.get<{ items: Txn[]; total: number }>("/api/transactions?limit=6"),
      api.get<Health>("/api/health"),
    ]);
    setBudgets(b);
    setRecent(t.items);
    setCount(t.total);
    setHealth(h);
  }

  useEffect(() => {
    load();
  }, []);

  async function genMockBank() {
    setBusy(true);
    setMsg("");
    try {
      const r = await api.post<{ inserted: number; skipped_duplicates: number }>(
        "/api/import/mock-bank?months=12",
      );
      setMsg(`Imported ${r.inserted} transactions (${r.skipped_duplicates} duplicates skipped).`);
      await load();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function uploadCsv(file: File) {
    setBusy(true);
    setMsg("");
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await api.postForm<{
        inserted: number;
        skipped_duplicates: number;
        rejected_rows: number;
      }>("/api/import/csv", form);
      setMsg(
        `CSV: +${r.inserted} added, ${r.skipped_duplicates} duplicates, ${r.rejected_rows} junk rows rejected.`,
      );
      await load();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const statusColor = {
    ok: "text-emerald-600 bg-emerald-50",
    warning: "text-amber-600 bg-amber-50",
    over: "text-red-600 bg-red-50",
  };

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Dashboard</h1>
        {health && (
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">
            LLM: {health.llm_mode} · search: {health.web_search}
          </span>
        )}
      </div>

      {/* Connect data */}
      <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
        <h2 className="font-medium text-slate-700">Connect your financial data</h2>
        <p className="mt-1 text-sm text-slate-400">
          Generate a realistic mock-bank history, or upload your own CSV of transactions.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            onClick={genMockBank}
            disabled={busy}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            Generate mock bank (12 mo)
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && uploadCsv(e.target.files[0])}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            Upload CSV
          </button>
          {msg && <span className="text-sm text-slate-500">{msg}</span>}
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <div className="text-sm text-slate-400">Transactions</div>
          <div className="mt-2 text-3xl font-semibold text-slate-800">{count}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 md:col-span-2">
          <div className="mb-3 text-sm font-medium text-slate-600">Budgets</div>
          {budgets.length === 0 && (
            <p className="text-sm text-slate-400">
              No budgets yet — set one on the{" "}
              <Link to="/budgets" className="text-brand-600">
                Budgets
              </Link>{" "}
              page.
            </p>
          )}
          <div className="space-y-2">
            {budgets.map((b) => (
              <div key={b.id} className="flex items-center justify-between text-sm">
                <span className="capitalize text-slate-600">{b.category}</span>
                <span className="text-slate-500">
                  {money(b.spent)} / {money(b.limit)}
                </span>
                <span className={`rounded-full px-2 py-0.5 text-xs ${statusColor[b.status]}`}>
                  {b.pct_used}%
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium text-slate-700">Recent transactions</h2>
          <Link to="/transactions" className="text-sm text-brand-600 hover:underline">
            View all
          </Link>
        </div>
        <div className="divide-y divide-slate-100">
          {recent.map((t) => (
            <div key={t.id} className="flex items-center justify-between py-2 text-sm">
              <div>
                <div className="font-medium text-slate-700">{t.merchant}</div>
                <div className="text-xs text-slate-400">
                  {shortDate(t.txn_date)} · {t.category}
                </div>
              </div>
              <div className={t.amount < 0 ? "text-slate-700" : "text-emerald-600"}>
                {money(t.amount, t.currency)}
              </div>
            </div>
          ))}
          {recent.length === 0 && (
            <p className="py-3 text-sm text-slate-400">No transactions yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}

import { FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import { money } from "../lib/format";

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

const BAR = { ok: "bg-emerald-500", warning: "bg-amber-500", over: "bg-red-500" };

export default function Budgets() {
  const [budgets, setBudgets] = useState<BudgetStatus[]>([]);
  const [category, setCategory] = useState("");
  const [limit, setLimit] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setBudgets(await api.get<BudgetStatus[]>("/api/budgets"));
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.post("/api/budgets", {
        category: category || null,
        period: "monthly",
        limit_amount: parseFloat(limit),
      });
      setCategory("");
      setLimit("");
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(id: number) {
    await api.del(`/api/budgets/${id}`);
    load();
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <h1 className="text-2xl font-semibold text-slate-800">Budgets</h1>
      <p className="mt-1 text-sm text-slate-400">
        Set monthly limits. The assistant warns you as you approach them.
      </p>

      <form
        onSubmit={create}
        className="mt-4 flex flex-wrap items-end gap-3 rounded-2xl border border-slate-200 bg-white p-4"
      >
        <div>
          <label className="block text-xs text-slate-500">Category (blank = overall)</label>
          <input
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="e.g. dining"
            className="mt-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500">Monthly limit</label>
          <input
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            placeholder="250"
            className="mt-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
            required
          />
        </div>
        <button className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
          Set budget
        </button>
        {error && <p className="w-full text-sm text-red-600">{error}</p>}
      </form>

      <div className="mt-6 space-y-4">
        {budgets.map((b) => (
          <div key={b.id} className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="flex items-center justify-between">
              <div className="font-medium capitalize text-slate-700">{b.category}</div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-slate-500">
                  {money(b.spent)} / {money(b.limit)}
                </span>
                <button
                  onClick={() => remove(b.id)}
                  className="text-xs text-slate-400 hover:text-red-500"
                >
                  delete
                </button>
              </div>
            </div>
            <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full ${BAR[b.status]}`}
                style={{ width: `${Math.min(100, b.pct_used)}%` }}
              />
            </div>
            <div className="mt-1 text-xs text-slate-400">
              {b.pct_used}% used · {money(b.remaining)} remaining
            </div>
          </div>
        ))}
        {budgets.length === 0 && (
          <p className="text-sm text-slate-400">No budgets yet.</p>
        )}
      </div>
    </div>
  );
}

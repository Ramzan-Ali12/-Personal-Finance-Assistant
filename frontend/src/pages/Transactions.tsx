import { FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import { money, shortDate } from "../lib/format";

interface Txn {
  id: number;
  txn_date: string;
  amount: number;
  merchant: string;
  description: string;
  category: string;
  currency: string;
  source: string;
}
interface Page {
  items: Txn[];
  total: number;
  limit: number;
  offset: number;
}

export default function Transactions() {
  const [page, setPage] = useState<Page | null>(null);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [showAdd, setShowAdd] = useState(false);
  const limit = 50;

  async function load() {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (search) q.set("search", search);
    setPage(await api.get<Page>(`/api/transactions?${q}`));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  function onSearch(e: FormEvent) {
    e.preventDefault();
    setOffset(0);
    load();
  }

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Transactions</h1>
        <button
          onClick={() => setShowAdd((s) => !s)}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          {showAdd ? "Close" : "Add transaction"}
        </button>
      </div>

      {showAdd && <AddForm onAdded={() => { setShowAdd(false); load(); }} />}

      <form onSubmit={onSearch} className="mt-4 flex gap-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search merchant…"
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
        />
        <button className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">
          Search
        </button>
      </form>

      <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-400">
            <tr>
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3">Merchant</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3 text-right">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {page?.items.map((t) => (
              <tr key={t.id} className="hover:bg-slate-50">
                <td className="px-4 py-2 text-slate-500">{shortDate(t.txn_date)}</td>
                <td className="px-4 py-2 font-medium text-slate-700">{t.merchant}</td>
                <td className="px-4 py-2">
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs capitalize text-slate-500">
                    {t.category}
                  </span>
                </td>
                <td
                  className={`px-4 py-2 text-right ${
                    t.amount < 0 ? "text-slate-700" : "text-emerald-600"
                  }`}
                >
                  {money(t.amount, t.currency)}
                </td>
              </tr>
            ))}
            {page?.items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-slate-400">
                  No transactions. Import data from the Dashboard.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {page && page.total > limit && (
        <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
          <span>
            {offset + 1}–{Math.min(offset + limit, page.total)} of {page.total}
          </span>
          <div className="flex gap-2">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
              className="rounded-lg border border-slate-200 px-3 py-1 disabled:opacity-40"
            >
              Prev
            </button>
            <button
              disabled={offset + limit >= page.total}
              onClick={() => setOffset(offset + limit)}
              className="rounded-lg border border-slate-200 px-3 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function AddForm({ onAdded }: { onAdded: () => void }) {
  const [form, setForm] = useState({
    txn_date: new Date().toISOString().slice(0, 10),
    amount: "",
    merchant: "",
    description: "",
    category: "",
  });
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.post("/api/transactions", {
        txn_date: form.txn_date,
        amount: parseFloat(form.amount),
        merchant: form.merchant,
        description: form.description,
        category: form.category || undefined,
      });
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mt-4 grid grid-cols-2 gap-3 rounded-2xl border border-slate-200 bg-white p-4 md:grid-cols-5"
    >
      <input
        type="date"
        value={form.txn_date}
        onChange={(e) => setForm({ ...form, txn_date: e.target.value })}
        className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
      />
      <input
        placeholder="Amount (− = spend)"
        value={form.amount}
        onChange={(e) => setForm({ ...form, amount: e.target.value })}
        className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        required
      />
      <input
        placeholder="Merchant"
        value={form.merchant}
        onChange={(e) => setForm({ ...form, merchant: e.target.value })}
        className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        required
      />
      <input
        placeholder="Category (optional)"
        value={form.category}
        onChange={(e) => setForm({ ...form, category: e.target.value })}
        className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
      />
      <button className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
        Save
      </button>
      {error && <p className="col-span-full text-sm text-red-600">{error}</p>}
    </form>
  );
}

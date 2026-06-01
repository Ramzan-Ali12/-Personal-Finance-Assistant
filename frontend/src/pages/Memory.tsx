import { useEffect, useState } from "react";
import { api } from "../api/client";

interface Ctx {
  id: number;
  key: string;
  value: string;
  raw_text: string;
  active: boolean;
}

export default function Memory() {
  const [items, setItems] = useState<Ctx[]>([]);

  async function load() {
    setItems(await api.get<Ctx[]>("/api/context"));
  }
  useEffect(() => {
    load();
  }, []);

  async function remove(id: number) {
    await api.del(`/api/context/${id}`);
    load();
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <h1 className="text-2xl font-semibold text-slate-800">Assistant memory</h1>
      <p className="mt-1 text-sm text-slate-400">
        Facts the assistant remembers about you and applies to its answers. Add new
        ones by telling the assistant, e.g. “remember that I get paid on the 1st” or
        “don’t count rent in my food budget”.
      </p>

      <div className="mt-6 space-y-3">
        {items.map((c) => (
          <div
            key={c.id}
            className="flex items-start justify-between rounded-2xl border border-slate-200 bg-white p-4"
          >
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-400">
                {c.key}
              </div>
              <div className="text-sm text-slate-700">{c.value}</div>
              {c.raw_text && c.raw_text !== c.value && (
                <div className="mt-1 text-xs italic text-slate-400">“{c.raw_text}”</div>
              )}
            </div>
            <button
              onClick={() => remove(c.id)}
              className="text-xs text-slate-400 hover:text-red-500"
            >
              forget
            </button>
          </div>
        ))}
        {items.length === 0 && (
          <p className="text-sm text-slate-400">
            Nothing remembered yet. Tell the assistant something to remember.
          </p>
        )}
      </div>
    </div>
  );
}

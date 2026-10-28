import { useState } from "react";
import { Button, Card } from "../ui";
import { CATEGORIES, categoryLabel } from "../../lib/categories";
import { translate, type MessageKey } from "../../i18n/core";
import { useI18n } from "../../i18n/useI18n";
import { useCategories, useCreateCategory, useDeleteCategory, useRenameCategory } from "../../hooks/useCategories";
import type { CategoryInfo } from "../../types";

const inputClass = "text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink";

/** "Gehalt" is the built-in "Salary" in German: such a name would look like a duplicate. */
function builtInNamed(name: string): string | null {
  const wanted = name.trim().toLocaleLowerCase();
  for (const category of CATEGORIES) {
    for (const lang of ["de", "en"] as const) {
      const label = translate(lang, `category.${category}` as MessageKey);
      if (label.toLocaleLowerCase() === wanted || category.toLocaleLowerCase() === wanted) return label;
    }
  }
  return null;
}

/** Create, rename and delete categories of one's own. */
export function CategoriesSection() {
  const { t } = useI18n();
  const { data } = useCategories();
  const create = useCreateCategory();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const own = (data ?? []).filter((c) => !c.built_in);

  function add(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    const clash = builtInNamed(name);
    if (clash) {
      setError(t("cats.isBuiltIn", { name: clash }));
      return;
    }
    setError(null);
    create.mutate(name, { onSuccess: () => setName(""), onError: (err) => setError((err as Error).message) });
  }

  return (
    <Card>
      <div className="px-5 py-4 border-b border-border space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">{t("cats.title")}</h2>
          <p className="text-xs text-ink-muted mt-1 max-w-lg">{t("cats.body")}</p>
        </div>
        <form onSubmit={add} className="flex flex-wrap items-center gap-2">
          <input
            aria-label={t("cats.newLabel")}
            placeholder={t("cats.newPlaceholder")}
            value={name}
            maxLength={40}
            onChange={(e) => setName(e.target.value)}
            className={inputClass}
          />
          <Button type="submit" variant="primary" className="!px-3 !py-1.5 text-xs" disabled={!name.trim() || create.isPending}>
            {create.isPending ? t("cats.adding") : t("cats.add")}
          </Button>
        </form>
        {error && <p className="text-xs text-danger">{error}</p>}
        {message && <p className="text-xs text-income">{message}</p>}
      </div>

      <div className="px-5 py-3 border-b border-border">
        <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">{t("cats.own")}</div>
        {own.length === 0 ? (
          <p className="text-sm text-ink-muted">{t("cats.none")}</p>
        ) : (
          <ul className="divide-y divide-border">
            {own.map((c) => (
              <OwnCategory key={c.id} category={c} all={data ?? []} onDeleted={setMessage} />
            ))}
          </ul>
        )}
      </div>

      <div className="px-5 py-3">
        <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">{t("cats.builtIn")}</div>
        <div className="flex flex-wrap gap-1.5">
          {CATEGORIES.map((c) => (
            <span key={c} className="text-xs rounded px-2 py-0.5 bg-surface-sunken text-ink-muted">
              {categoryLabel(t, c)}
            </span>
          ))}
        </div>
      </div>
    </Card>
  );
}

function OwnCategory({
  category,
  all,
  onDeleted,
}: {
  category: CategoryInfo;
  all: CategoryInfo[];
  onDeleted: (message: string) => void;
}) {
  const { t, tn } = useI18n();
  const rename = useRenameCategory();
  const remove = useDeleteCategory();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(category.name);
  const [deleting, setDeleting] = useState(false);
  const [replacement, setReplacement] = useState("");
  const [error, setError] = useState<string | null>(null);
  const id = category.id as number;

  function save() {
    const clash = builtInNamed(name);
    if (clash) {
      setError(t("cats.isBuiltIn", { name: clash }));
      return;
    }
    rename.mutate(
      { id, name },
      { onSuccess: () => { setEditing(false); setError(null); }, onError: (err) => setError((err as Error).message) }
    );
  }

  return (
    <li className="py-2.5 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {editing ? (
          <div className="flex items-center gap-2">
            <input
              aria-label={t("cats.nameOf", { name: category.name })}
              value={name}
              maxLength={40}
              autoFocus
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && save()}
              className={inputClass}
            />
            <Button variant="primary" className="!px-2.5 !py-1 text-xs" disabled={!name.trim() || rename.isPending} onClick={save}>
              {t("common.save")}
            </Button>
            <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => { setEditing(false); setName(category.name); setError(null); }}>
              {t("common.cancel")}
            </Button>
          </div>
        ) : (
          <div className="text-sm text-ink">
            {category.name} <span className="text-xs text-ink-faint ml-1">{tn("cats.count", category.transaction_count)}</span>
          </div>
        )}
        {!editing && !deleting && (
          <div className="flex gap-1">
            <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setEditing(true)}>
              {t("cats.rename")}
            </Button>
            <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setDeleting(true)}>
              {t("cats.delete")}
            </Button>
          </div>
        )}
      </div>
      {error && <p className="text-xs text-danger">{error}</p>}
      {deleting && (
        <div className="rounded-md bg-danger-soft border border-danger/30 p-3 space-y-2">
          <p className="text-sm text-ink">{tn("cats.deleteConfirm", category.transaction_count, { name: category.name })}</p>
          <label className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
            {t("cats.replacement")}
            <select value={replacement} onChange={(e) => setReplacement(e.target.value)} className={inputClass}>
              <option value="">{t("cats.replacementNone")}</option>
              {all.filter((c) => c.name !== category.name).map((c) => (
                <option key={c.name} value={c.name}>
                  {categoryLabel(t, c.name)}
                </option>
              ))}
            </select>
          </label>
          {remove.isError && <p className="text-xs text-danger">{(remove.error as Error).message}</p>}
          <div className="flex gap-2">
            <Button
              variant="primary"
              className="!bg-danger hover:!bg-danger !px-2.5 !py-1 text-xs"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(
                  { id, replacement: replacement || null },
                  { onSuccess: (result) => onDeleted(tn("cats.deleted", result.transactions_moved)) }
                )
              }
            >
              {t("cats.deleteYes")}
            </Button>
            <Button variant="ghost" className="!px-2.5 !py-1 text-xs" onClick={() => setDeleting(false)} disabled={remove.isPending}>
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

import type { PropsWithChildren } from "react";
import clsx from "clsx";
import { useI18n } from "../../i18n/useI18n";

export function Card({ children, className }: PropsWithChildren<{ className?: string }>) {
  return (
    <div className={clsx("bg-surface border border-border rounded-lg", className)}>
      {children}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between px-8 pt-7 pb-5 border-b border-border bg-surface">
      <div>
        <h1 className="text-lg font-semibold text-ink tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-ink-muted mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

type BadgeTone = "neutral" | "income" | "expense" | "warning" | "danger" | "accent";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-surface-sunken text-ink-muted",
  income: "bg-income-soft text-income",
  expense: "bg-expense-soft text-expense",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  accent: "bg-accent-soft text-accent-strong",
};

export function Badge({ tone = "neutral", children }: PropsWithChildren<{ tone?: BadgeTone }>) {
  return (
    <span className={clsx("inline-flex items-center px-2 py-0.5 rounded text-xs font-medium", TONE_CLASSES[tone])}>
      {children}
    </span>
  );
}

export function Button({
  children,
  variant = "primary",
  className,
  ...rest
}: PropsWithChildren<{ variant?: "primary" | "secondary" | "ghost" | "danger" } & React.ButtonHTMLAttributes<HTMLButtonElement>>) {
  const base = "inline-flex items-center gap-1.5 px-3.5 py-2 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
  const variants = {
    primary: "bg-accent text-white hover:bg-accent-strong",
    secondary: "bg-surface border border-border-strong text-ink hover:bg-surface-sunken",
    ghost: "text-ink-muted hover:bg-surface-sunken hover:text-ink",
    danger: "bg-danger text-white hover:bg-danger/90",
  };
  return (
    <button className={clsx(base, variants[variant], className)} {...rest}>
      {children}
    </button>
  );
}

export function ReconciliationStatusBadge({ status }: { status: "reconciled" | "mismatch" | "unresolved" | "pending" }) {
  const { t } = useI18n();
  if (status === "reconciled") return <Badge tone="income">{t("status.reconciled")}</Badge>;
  if (status === "mismatch") return <Badge tone="danger">{t("status.mismatch")}</Badge>;
  if (status === "unresolved") return <Badge tone="warning">{t("status.unresolved")}</Badge>;
  return <Badge tone="neutral">{t("status.pending")}</Badge>;
}

/** A request failed: say so (instead of "no data" or loading forever) and offer to try again. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div role="alert" className="flex flex-col items-center justify-center text-center py-12 px-6">
      <div className="text-sm font-medium text-danger">{t("error.loadFailed")}</div>
      <div className="text-sm text-ink-muted mt-1 max-w-md">{error instanceof Error ? error.message : String(error)}</div>
      {onRetry && (
        <button type="button" onClick={onRetry} className="mt-3 text-sm text-accent-strong underline underline-offset-2">
          {t("error.retry")}
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      <div className="text-sm font-medium text-ink">{title}</div>
      {description && <div className="text-sm text-ink-muted mt-1 max-w-sm">{description}</div>}
    </div>
  );
}

/** Previous / "page x of y" / next. */
export function Pager({ page, pages, onChange }: { page: number; pages: number; onChange: (page: number) => void }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-3 text-xs text-ink-muted">
      <button type="button" className="disabled:opacity-40" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        {t("tx.previous")}
      </button>
      <span>{t("tx.page", { page, pages })}</span>
      <button type="button" className="disabled:opacity-40" disabled={page >= pages} onClick={() => onChange(page + 1)}>
        {t("tx.next")}
      </button>
    </div>
  );
}

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, ArrowDownRight, ArrowUpRight, RefreshCw } from "lucide-react";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { SkeletonLines } from "../../components/ui/Spinner";
import type { AdminQueryState } from "../hooks/useAdminQuery";
import { formatNumber, formatRelative } from "../lib/format";

// ── Page header ─────────────────────────────────────────────────────────────

export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: { label: string; to: string };
}) {
  return (
    <header className="adm-page-header">
      <div className="adm-page-heading">
        {breadcrumb ? (
          <Link className="adm-breadcrumb" to={breadcrumb.to}>
            ← {breadcrumb.label}
          </Link>
        ) : null}
        <h1 className="adm-page-title">{title}</h1>
        {description ? <p className="adm-page-description">{description}</p> : null}
      </div>
      {actions ? <div className="adm-page-actions">{actions}</div> : null}
    </header>
  );
}

// ── Live data indicator ─────────────────────────────────────────────────────

export function LiveIndicator({ query, label = "Live" }: { query: AdminQueryState<unknown>; label?: string }) {
  const [, force] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => force((value) => value + 1), 5000);
    return () => window.clearInterval(id);
  }, []);

  let state: "live" | "refreshing" | "stale" | "reconnecting" | "loading" = "live";
  let text = `${label} · updated ${formatRelative(query.lastUpdatedAt)}`;
  if (query.status === "loading") {
    state = "loading";
    text = "Loading…";
  } else if (query.error && query.data) {
    state = "reconnecting";
    text = `Reconnecting · last update ${formatRelative(query.lastUpdatedAt)}`;
  } else if (query.isStale) {
    state = "stale";
    text = `Stale · last update ${formatRelative(query.lastUpdatedAt)}`;
  } else if (query.isRefreshing) {
    state = "refreshing";
  }

  return (
    <span className={`adm-live is-${state}`} role="status" aria-live="polite">
      <span className="adm-live-dot" aria-hidden="true" />
      {text}
      <button
        type="button"
        className="adm-live-refresh"
        onClick={query.refetch}
        aria-label="Refresh now"
        title="Refresh now"
      >
        <RefreshCw size={13} aria-hidden="true" className={query.isRefreshing ? "is-spinning" : undefined} />
      </button>
    </span>
  );
}

// ── Query states ───────────────────────────────────────────────────────────

export function errorMessage(error: Error | null): string {
  if (!error) return "";
  if (error instanceof ApiError) {
    if (error.code === "http_error") return `The admin API returned an error (HTTP ${error.status}).`;
    return error.message;
  }
  // fetch() rejects with a TypeError when the server is unreachable.
  if (error instanceof TypeError) return "The admin API could not be reached. Check the gateway.";
  return "Something went wrong while loading this data.";
}

export function ErrorState({ error, onRetry }: { error: Error | null; onRetry?: () => void }) {
  return (
    <EmptyState
      icon={<AlertCircle size={20} />}
      title="Couldn't load this data"
      description={errorMessage(error)}
      action={onRetry ? <Button size="sm" onClick={onRetry}>Try again</Button> : undefined}
    />
  );
}

/** Loading skeleton → error with retry → children(data). Keeps data visible while refreshing. */
export function QueryBoundary<T>({
  query,
  children,
  skeletonLines = 6,
}: {
  query: AdminQueryState<T>;
  children: (data: T) => ReactNode;
  skeletonLines?: number;
}) {
  if (query.data !== null) return <>{children(query.data)}</>;
  if (query.status === "error") return <ErrorState error={query.error} onRetry={query.refetch} />;
  return (
    <div className="adm-skeleton" role="status" aria-label="Loading">
      <SkeletonLines count={skeletonLines} />
    </div>
  );
}

export function Unavailable({ title = "Not available", children }: { title?: string; children: ReactNode }) {
  return (
    <div className="adm-unavailable">
      <p className="adm-unavailable-title">{title}</p>
      <p>{children}</p>
    </div>
  );
}

// ── Sections & key-value lists ────────────────────────────────────────────

export function Section({
  title,
  description,
  actions,
  children,
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section className="adm-section" aria-labelledby={headingId}>
      <div className="adm-section-header">
        <div>
          <h2 className="adm-section-title" id={headingId}>{title}</h2>
          {description ? <p className="adm-section-description">{description}</p> : null}
        </div>
        {actions ? <div className="adm-section-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function KeyValueList({ items }: { items: Array<{ label: string; value: ReactNode }> }) {
  return (
    <dl className="adm-kv">
      {items.map((item) => (
        <div className="adm-kv-row" key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

// ── Metric tile ────────────────────────────────────────────────────────────

interface MetricTileProps {
  label: string;
  value: number | null | undefined;
  /** Same metric over the comparison period; only shown when real data exists. */
  previous?: number | null;
  previousLabel?: string;
  /** "down" when a decrease is good (errors). */
  goodDirection?: "up" | "down";
  available?: boolean;
  note?: string | null;
  href?: string;
  emphasis?: "danger" | "warning" | null;
  format?: (value: number) => string;
}

export function MetricTile({
  label,
  value,
  previous,
  previousLabel = "vs previous",
  goodDirection = "up",
  available = true,
  note,
  href,
  emphasis,
  format = (number) => formatNumber(number),
}: MetricTileProps) {
  const hasDelta = available && typeof value === "number" && typeof previous === "number";
  const delta = hasDelta ? (value as number) - (previous as number) : 0;
  const deltaTone = delta === 0 ? "neutral" : (delta > 0) === (goodDirection === "up") ? "good" : "bad";
  const body = (
    <>
      <span className="adm-metric-label">{label}</span>
      <span className={["adm-metric-value", emphasis ? `is-${emphasis}` : ""].filter(Boolean).join(" ")}>
        {available && typeof value === "number" ? format(value) : "—"}
      </span>
      {!available ? (
        <span className="adm-metric-meta">Not available</span>
      ) : hasDelta ? (
        <span className={`adm-metric-delta is-${deltaTone}`}>
          {delta > 0 ? <ArrowUpRight size={12} aria-hidden="true" /> : delta < 0 ? <ArrowDownRight size={12} aria-hidden="true" /> : null}
          {delta === 0 ? "No change" : `${delta > 0 ? "+" : ""}${formatNumber(delta)}`} {previousLabel}
        </span>
      ) : note ? (
        <span className="adm-metric-meta">{note}</span>
      ) : null}
    </>
  );
  if (href) {
    return (
      <Link to={href} className="adm-metric is-link" title={note ?? undefined}>
        {body}
      </Link>
    );
  }
  return (
    <div className="adm-metric" title={note ?? undefined}>
      {body}
    </div>
  );
}

// ── Filters ────────────────────────────────────────────────────────────────

export function FilterBar({ children, trailing }: { children: ReactNode; trailing?: ReactNode }) {
  return (
    <div className="adm-filters" role="search">
      <div className="adm-filters-main">{children}</div>
      {trailing ? <div className="adm-filters-trailing">{trailing}</div> : null}
    </div>
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  label: string;
}) {
  const [draft, setDraft] = useState(value);
  const timer = useRef<number | null>(null);
  useEffect(() => setDraft(value), [value]);
  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
  }, []);
  return (
    <input
      className="input adm-search"
      type="search"
      aria-label={label}
      placeholder={placeholder}
      value={draft}
      onChange={(event) => {
        const next = event.target.value;
        setDraft(next);
        if (timer.current !== null) window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => onChange(next.trim()), 300);
      }}
    />
  );
}

// ── Tabs ───────────────────────────────────────────────────────────────────

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  label,
  idPrefix,
}: {
  tabs: Array<{ id: T; label: string; count?: number | null }>;
  active: T;
  onChange: (id: T) => void;
  label: string;
  idPrefix: string;
}) {
  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    const next = tabs[(index + delta + tabs.length) % tabs.length];
    onChange(next.id);
    document.getElementById(`${idPrefix}-tab-${next.id}`)?.focus();
  }
  return (
    <div className="tabs adm-tabs" role="tablist" aria-label={label}>
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          id={`${idPrefix}-tab-${tab.id}`}
          type="button"
          role="tab"
          className="tab"
          aria-selected={active === tab.id}
          aria-controls={`${idPrefix}-panel`}
          tabIndex={active === tab.id ? 0 : -1}
          onClick={() => onChange(tab.id)}
          onKeyDown={(event) => handleKeyDown(event, index)}
        >
          {tab.label}
          {typeof tab.count === "number" && tab.count > 0 ? <span className="tab-count">{formatNumber(tab.count)}</span> : null}
        </button>
      ))}
    </div>
  );
}

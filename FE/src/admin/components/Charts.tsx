import { useId, useState } from "react";
import { formatNumber } from "../lib/format";

// Single-series charts: one hue (--color-chart-bar, validated for both themes),
// no legend (the section title names the series), text always in ink tokens,
// hover tooltip on every mark, and a table view for screen readers / exact values.

function niceStep(max: number, targetTicks = 4): number {
  if (max <= 0) return 1;
  const raw = max / targetTicks;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return Math.max(1, nice * magnitude);
}

export function niceTicks(max: number): number[] {
  const step = niceStep(max);
  const top = Math.max(step, Math.ceil(max / step) * step);
  const ticks: number[] = [];
  for (let value = 0; value <= top; value += step) ticks.push(value);
  return ticks;
}

function TableToggle({ shown, onToggle, controls }: { shown: boolean; onToggle: () => void; controls: string }) {
  return (
    <button type="button" className="adm-chart-toggle" aria-expanded={shown} aria-controls={controls} onClick={onToggle}>
      {shown ? "Hide table" : "Show table"}
    </button>
  );
}

export interface ColumnDatum {
  key: string;
  label: string;
  /** Shorter axis label; falls back to label. */
  axisLabel?: string;
  value: number;
}

export function ColumnChart({
  data,
  valueLabel,
  ariaLabel,
}: {
  data: ColumnDatum[];
  valueLabel: string;
  ariaLabel: string;
}) {
  const [active, setActive] = useState<string | null>(null);
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();
  const max = Math.max(0, ...data.map((datum) => datum.value));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const labelEvery = Math.max(1, Math.ceil(data.length / 8));
  const activeDatum = data.find((datum) => datum.key === active) ?? null;

  return (
    <div className="adm-chart">
      <div className="adm-chart-toolbar">
        <TableToggle shown={showTable} onToggle={() => setShowTable((value) => !value)} controls={tableId} />
      </div>
      <div className="adm-columns" role="img" aria-label={ariaLabel}>
        <div className="adm-columns-axis" aria-hidden="true">
          <div className="adm-columns-axis-scale">
            {ticks.map((tick) => (
              <span key={tick} style={{ bottom: `${(tick / top) * 100}%` }}>{formatNumber(tick)}</span>
            ))}
          </div>
        </div>
        <div className="adm-columns-plot" onMouseLeave={() => setActive(null)}>
          <div className="adm-columns-bars">
            {ticks.map((tick) => (
              <span key={tick} className="adm-columns-grid" style={{ bottom: `${(tick / top) * 100}%` }} aria-hidden="true" />
            ))}
            {data.map((datum, index) => (
              <div
                key={datum.key}
                className={["adm-columns-slot", active === datum.key ? "is-active" : ""].filter(Boolean).join(" ")}
                onMouseEnter={() => setActive(datum.key)}
              >
                <span className="adm-columns-bar" style={{ height: `${(datum.value / top) * 100}%` }} />
                <span className="adm-columns-label" aria-hidden="true">
                  {index % labelEvery === 0 ? datum.axisLabel ?? datum.label : ""}
                </span>
              </div>
            ))}
          </div>
          {activeDatum ? (
            <div
              className="adm-chart-tooltip"
              style={{ left: `${((data.indexOf(activeDatum) + 0.5) / data.length) * 100}%` }}
              aria-hidden="true"
            >
              <strong>{formatNumber(activeDatum.value)}</strong> {valueLabel}
              <span>{activeDatum.label}</span>
            </div>
          ) : null}
        </div>
      </div>
      <div id={tableId} hidden={!showTable}>
        <table className="adm-table adm-chart-table">
          <caption className="sr-only">{ariaLabel}</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col" className="is-right">{valueLabel}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((datum) => (
              <tr key={datum.key}>
                <td>{datum.label}</td>
                <td className="is-right">{formatNumber(datum.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export interface BarDatum {
  key: string;
  label: string;
  value: number;
}

export function BarList({ data, valueLabel, ariaLabel }: { data: BarDatum[]; valueLabel: string; ariaLabel: string }) {
  const max = Math.max(0, ...data.map((datum) => datum.value));
  const total = data.reduce((sum, datum) => sum + datum.value, 0);
  return (
    <table className="adm-barlist">
      <caption className="sr-only">{ariaLabel}</caption>
      <thead className="sr-only">
        <tr>
          <th scope="col">Category</th>
          <th scope="col">{valueLabel}</th>
        </tr>
      </thead>
      <tbody>
        {data.map((datum) => {
          const share = total > 0 ? Math.round((datum.value / total) * 100) : 0;
          return (
            <tr key={datum.key} title={`${datum.label}: ${formatNumber(datum.value)} ${valueLabel} (${share}%)`}>
              <th scope="row" className="adm-barlist-label">{datum.label}</th>
              <td className="adm-barlist-cell">
                <span className="adm-barlist-track">
                  <span
                    className="adm-barlist-bar"
                    style={{ width: max > 0 ? `${Math.max(datum.value > 0 ? 1.5 : 0, (datum.value / max) * 100)}%` : "0%" }}
                  />
                </span>
                <span className="adm-barlist-value">
                  {formatNumber(datum.value)}
                  <span className="adm-barlist-share">{share}%</span>
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

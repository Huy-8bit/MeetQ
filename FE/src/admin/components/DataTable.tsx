import type { MouseEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  align?: "left" | "right";
  /** Hidden below the tablet breakpoint to keep tables readable. */
  hideOnNarrow?: boolean;
  className?: string;
}

interface DataTableProps<T> {
  caption: string;
  columns: Array<Column<T>>;
  rows: T[];
  getRowKey: (row: T) => string;
  /**
   * Whole-row click target for mouse users. Keyboard and screen-reader users
   * navigate through the link rendered in the row's first cell.
   */
  getRowHref?: (row: T) => string;
  empty?: ReactNode;
  busy?: boolean;
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  getRowKey,
  getRowHref,
  empty,
  busy = false,
}: DataTableProps<T>) {
  const navigate = useNavigate();

  if (rows.length === 0 && empty) {
    return <div className="adm-table-empty">{empty}</div>;
  }

  function handleRowClick(event: MouseEvent<HTMLTableRowElement>, href: string) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button, input, [role='button']")) return;
    if (window.getSelection()?.toString()) return;
    navigate(href);
  }

  return (
    <div className="adm-table-scroll" aria-busy={busy || undefined}>
      <table className="adm-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={[
                  column.align === "right" ? "is-right" : "",
                  column.hideOnNarrow ? "hide-narrow" : "",
                  column.className ?? "",
                ].filter(Boolean).join(" ") || undefined}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const href = getRowHref?.(row);
            return (
              <tr
                key={getRowKey(row)}
                className={href ? "is-link" : undefined}
                onClick={href ? (event) => handleRowClick(event, href) : undefined}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={[
                      column.align === "right" ? "is-right" : "",
                      column.hideOnNarrow ? "hide-narrow" : "",
                      column.className ?? "",
                    ].filter(Boolean).join(" ") || undefined}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) {
    return <p className="adm-pagination-summary">{total} {total === 1 ? "result" : "results"}</p>;
  }
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <nav className="adm-pagination" aria-label="Pagination">
      <p className="adm-pagination-summary">
        {from}–{to} of {total}
      </p>
      <div className="adm-pagination-buttons">
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
        >
          Previous
        </button>
        <span className="adm-pagination-page" aria-current="page">
          Page {page} of {pageCount}
        </span>
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pageCount}
        >
          Next
        </button>
      </div>
    </nav>
  );
}

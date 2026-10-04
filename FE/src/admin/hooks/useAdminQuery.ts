import { useCallback, useEffect, useRef, useState } from "react";

export interface AdminQueryState<T> {
  data: T | null;
  error: Error | null;
  /** loading = first load with no data yet. */
  status: "loading" | "success" | "error";
  /** A request is in flight while data is already shown. */
  isRefreshing: boolean;
  lastUpdatedAt: number | null;
  /** Data is shown but the latest poll failed or is overdue. */
  isStale: boolean;
  refetch: () => void;
}

interface Options {
  /** Poll interval; omit for fetch-once. */
  intervalMs?: number;
  enabled?: boolean;
}

const STALE_AFTER_INTERVALS = 3;

/**
 * Fetch + optional polling for admin pages.
 * - `key` identifies the query; changing it refetches while keeping the old data visible.
 * - Polling pauses while the tab is hidden and resumes with an immediate refresh.
 * - Out-of-order responses are ignored; timers are cleared on unmount.
 */
export function useAdminQuery<T>(
  key: string,
  fetcher: () => Promise<T>,
  { intervalMs, enabled = true }: Options = {},
): AdminQueryState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const sequenceRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const run = useCallback(async () => {
    clearTimer();
    const sequence = ++sequenceRef.current;
    setInFlight(true);
    try {
      const result = await fetcherRef.current();
      if (!mountedRef.current || sequence !== sequenceRef.current) return;
      setData(result);
      setError(null);
      const at = Date.now();
      setLastUpdatedAt(at);
      setNow(at);
    } catch (caught) {
      if (!mountedRef.current || sequence !== sequenceRef.current) return;
      setError(caught instanceof Error ? caught : new Error("Request failed"));
    } finally {
      if (mountedRef.current && sequence === sequenceRef.current) {
        setInFlight(false);
        if (intervalMs && !document.hidden) {
          timerRef.current = window.setTimeout(() => {
            void run();
          }, intervalMs);
        }
      }
    }
  }, [intervalMs]);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) return undefined;
    void run();
    return () => {
      sequenceRef.current += 1;
      clearTimer();
    };
  }, [key, enabled, run]);

  useEffect(() => {
    if (!intervalMs || !enabled) return undefined;
    const handleVisibility = () => {
      if (document.hidden) {
        clearTimer();
      } else {
        void run();
      }
    };
    const tick = window.setInterval(() => setNow(Date.now()), Math.min(intervalMs, 5000));
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      window.clearInterval(tick);
    };
  }, [enabled, intervalMs, run]);

  useEffect(
    () => () => {
      mountedRef.current = false;
      clearTimer();
    },
    [],
  );

  const overdue =
    !!intervalMs && lastUpdatedAt !== null && now - lastUpdatedAt > intervalMs * STALE_AFTER_INTERVALS;

  return {
    data,
    error,
    status: data !== null ? "success" : error ? "error" : "loading",
    isRefreshing: inFlight && data !== null,
    lastUpdatedAt,
    isStale: data !== null && (error !== null || overdue),
    refetch: () => {
      void run();
    },
  };
}

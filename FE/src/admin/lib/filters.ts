import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import type { CustomSelectOption } from "../../components/CustomSelect";
import { SUPPORTED_MEETING_LANGUAGES, getLanguageLabel } from "../../lib/languages";
import type { AiMode } from "../api/types";
import { AI_MODE_LABELS } from "./format";

/** Filters live in the URL so a filtered view can be shared or reloaded. */
export function useUrlFilters<K extends string>(keys: readonly K[]) {
  const [params, setParams] = useSearchParams();
  const values = Object.fromEntries(keys.map((key) => [key, params.get(key) ?? ""])) as Record<K, string>;
  const page = Math.max(1, Number(params.get("page")) || 1);

  const setFilter = useCallback(
    (key: K | "page", value: string | number) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          if (value === "" || value === null) next.delete(key);
          else next.set(key, String(value));
          if (key !== "page") next.delete("page");
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const clear = useCallback(() => setParams(new URLSearchParams(), { replace: true }), [setParams]);
  const active = keys.some((key) => values[key] !== "");
  return { values, page, setFilter, clear, active };
}

export const LANGUAGE_OPTIONS: CustomSelectOption[] = [
  { value: "", label: "All languages" },
  ...SUPPORTED_MEETING_LANGUAGES.map((code) => ({ value: code, label: getLanguageLabel(code) })),
];

export const AI_MODE_OPTIONS: CustomSelectOption[] = [
  { value: "", label: "All AI modes" },
  ...(["voice_text", "text_only", "captions", "summary_capture", "off"] as AiMode[]).map((mode) => ({
    value: mode,
    label: AI_MODE_LABELS[mode],
  })),
];

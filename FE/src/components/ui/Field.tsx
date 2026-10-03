import type { ReactNode } from "react";

interface FieldProps {
  label: ReactNode;
  /** id of the control the label points at. */
  htmlFor?: string;
  helper?: ReactNode;
  error?: ReactNode;
  /** Render the label as a plain heading for grouped controls (no `for`). */
  asGroup?: boolean;
  labelId?: string;
  children: ReactNode;
}

export function Field({ label, htmlFor, helper, error, asGroup = false, labelId, children }: FieldProps) {
  return (
    <div className="field">
      {asGroup ? (
        <span className="field-label" id={labelId}>
          {label}
        </span>
      ) : (
        <label className="field-label" htmlFor={htmlFor} id={labelId}>
          {label}
        </label>
      )}
      {children}
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : helper ? (
        <p className="field-helper">{helper}</p>
      ) : null}
    </div>
  );
}

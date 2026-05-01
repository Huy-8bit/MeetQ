interface BrseToggleControlProps {
  enabled: boolean;
  pending?: boolean;
  disabled?: boolean;
  onToggle: (nextEnabled: boolean) => void;
}

export function BrseToggleControl({
  enabled,
  pending = false,
  disabled = false,
  onToggle,
}: BrseToggleControlProps) {
  const label = enabled ? "BRSE On" : "BRSE Off";

  return (
    <button
      className={`brse-toggle-control ${enabled ? "is-on" : "is-off"}`}
      type="button"
      aria-pressed={enabled}
      disabled={disabled || pending}
      onClick={() => onToggle(!enabled)}
    >
      <span className="brse-toggle-copy">
        <strong>{pending ? "Updating" : label}</strong>
        <span>{enabled ? "AI relay active" : "Normal meeting"}</span>
      </span>
      <span className="brse-toggle-track" aria-hidden="true">
        <span className="brse-toggle-thumb" />
      </span>
    </button>
  );
}

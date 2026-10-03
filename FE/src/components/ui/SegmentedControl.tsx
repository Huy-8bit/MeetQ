import { useRef, type KeyboardEvent } from "react";

export interface SegmentedOption<TValue extends string> {
  value: TValue;
  label: string;
  disabled?: boolean;
  /** Tooltip, e.g. why an option is disabled. */
  title?: string;
}

interface SegmentedControlProps<TValue extends string> {
  value: TValue;
  options: Array<SegmentedOption<TValue>>;
  onChange: (value: TValue) => void;
  ariaLabel?: string;
  ariaLabelledBy?: string;
  disabled?: boolean;
}

/** Single-choice radio group with arrow-key navigation. */
export function SegmentedControl<TValue extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  ariaLabelledBy,
  disabled = false,
}: SegmentedControlProps<TValue>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const enabled = options.map((option) => !option.disabled && !disabled);
  const selectedIndex = options.findIndex((option) => option.value === value);
  const focusIndex = selectedIndex >= 0 && enabled[selectedIndex] ? selectedIndex : enabled.indexOf(true);

  function move(from: number, delta: number) {
    for (let step = 1; step <= options.length; step++) {
      const next = (from + delta * step + options.length) % options.length;
      if (enabled[next]) {
        onChange(options[next].value);
        refs.current[next]?.focus();
        return;
      }
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      move(index, 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      move(index, -1);
    }
  }

  return (
    <div className="segmented" role="radiogroup" aria-label={ariaLabel} aria-labelledby={ariaLabelledBy}>
      {options.map((option, index) => (
        <button
          key={option.value}
          ref={(node) => {
            refs.current[index] = node;
          }}
          type="button"
          role="radio"
          className="segmented-option"
          aria-checked={option.value === value}
          tabIndex={index === focusIndex ? 0 : -1}
          disabled={!enabled[index]}
          title={option.title}
          onClick={() => onChange(option.value)}
          onKeyDown={(event) => handleKeyDown(event, index)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

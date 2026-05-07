import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

export interface CustomSelectOption<TValue extends string = string> {
  value: TValue;
  label: string;
  helper?: string;
  disabled?: boolean;
}

interface CustomSelectProps<TValue extends string = string> {
  value: TValue;
  options: Array<CustomSelectOption<TValue>>;
  onChange: (value: TValue) => void;
  placeholder?: string;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
  size?: "standard" | "compact";
}

export function CustomSelect<TValue extends string = string>({
  value,
  options,
  onChange,
  placeholder = "Select",
  disabled = false,
  ariaLabel,
  className,
  size = "standard",
}: CustomSelectProps<TValue>) {
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const selectedOption = useMemo(
    () => options.find((option) => option.value === value),
    [options, value],
  );
  const hasSelection = value !== "" && !!selectedOption;
  const enabledOptions = options.filter((option) => !option.disabled);
  const hasEnabledOptions = enabledOptions.length > 0;
  const activeOption = activeIndex >= 0 ? options[activeIndex] : null;
  const currentLabel = hasSelection ? selectedOption?.label ?? placeholder : placeholder;

  useEffect(() => {
    if (!open) {
      return;
    }

    const selectedIndex = options.findIndex((option) => option.value === value && !option.disabled);
    const firstEnabledIndex = options.findIndex((option) => !option.disabled);
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : firstEnabledIndex);
  }, [open, options, value]);

  useEffect(() => {
    if (!open || typeof document === "undefined") {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [open]);

  function commitOption(option: CustomSelectOption<TValue>) {
    if (option.disabled) {
      return;
    }

    onChange(option.value);
    setOpen(false);
  }

  function moveActive(delta: number) {
    if (!hasEnabledOptions) {
      return;
    }

    setActiveIndex((current) => {
      const startIndex = current >= 0 ? current : 0;
      for (let offset = 1; offset <= options.length; offset += 1) {
        const nextIndex = (startIndex + delta * offset + options.length) % options.length;
        if (!options[nextIndex]?.disabled) {
          return nextIndex;
        }
      }
      return current;
    });
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) {
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
      } else {
        moveActive(1);
      }
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
      } else {
        moveActive(-1);
      }
      return;
    }

    if (event.key === "Home") {
      event.preventDefault();
      const firstEnabledIndex = options.findIndex((option) => !option.disabled);
      if (firstEnabledIndex >= 0) {
        setActiveIndex(firstEnabledIndex);
      }
      return;
    }

    if (event.key === "End") {
      event.preventDefault();
      for (let index = options.length - 1; index >= 0; index -= 1) {
        if (!options[index]?.disabled) {
          setActiveIndex(index);
          break;
        }
      }
      return;
    }

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      if (activeOption) {
        commitOption(activeOption);
      }
      return;
    }

    if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div
      ref={rootRef}
      className={[
        "custom-select",
        `custom-select-${size}`,
        open ? "is-open" : "",
        hasSelection ? "has-value" : "",
        disabled ? "is-disabled" : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
      onBlur={(event) => {
        const nextTarget = event.relatedTarget as Node | null;
        if (!event.currentTarget.contains(nextTarget)) {
          setOpen(false);
        }
      }}
    >
      <button
        type="button"
        className="custom-select-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => {
          if (!disabled) {
            setOpen((current) => !current);
          }
        }}
        onKeyDown={handleKeyDown}
      >
        <span className={hasSelection ? "custom-select-value" : "custom-select-placeholder"}>
          {currentLabel}
        </span>
        <span className="custom-select-chevrons" aria-hidden="true">
          <span />
          <span />
        </span>
      </button>

      {open ? (
        <div
          id={listboxId}
          className="custom-select-menu"
          role="listbox"
          aria-label={ariaLabel}
          aria-activedescendant={
            activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined
          }
        >
          {options.map((option, index) => {
            const selected = option.value === value;
            const active = index === activeIndex;
            return (
              <button
                id={`${listboxId}-option-${index}`}
                key={option.value || `empty-${index}`}
                type="button"
                role="option"
                aria-selected={selected}
                disabled={option.disabled}
                className={[
                  "custom-select-option",
                  selected ? "is-selected" : "",
                  active ? "is-active" : "",
                ].filter(Boolean).join(" ")}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => commitOption(option)}
              >
                <span className="custom-select-option-label">{option.label}</span>
                {option.helper ? (
                  <span className="custom-select-option-helper">{option.helper}</span>
                ) : null}
                {selected ? <span className="custom-select-check" aria-hidden="true" /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

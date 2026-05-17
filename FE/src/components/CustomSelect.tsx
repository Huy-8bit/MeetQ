import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MutableRefObject,
} from "react";
import { createPortal } from "react-dom";
import { useDropdownMotion } from "../lib/motion";

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
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const menuMotionRef = useDropdownMotion<HTMLDivElement>(open);
  const [activeIndex, setActiveIndex] = useState(-1);

  // Merge motion ref and our own menuRef
  const setMenuRef = (node: HTMLDivElement | null) => {
    menuRef.current = node;
    (menuMotionRef as MutableRefObject<HTMLDivElement | null>).current = node;
  };

  const selectedOption = useMemo(
    () => options.find((o) => o.value === value),
    [options, value],
  );
  const hasSelection = value !== "" && !!selectedOption;
  const enabledOptions = options.filter((o) => !o.disabled);
  const hasEnabledOptions = enabledOptions.length > 0;
  const activeOption = activeIndex >= 0 ? options[activeIndex] : null;
  const currentLabel = hasSelection ? selectedOption?.label ?? placeholder : placeholder;

  // Position the portal menu by setting CSS custom properties directly on the
  // DOM node — avoids the "no inline styles" lint rule entirely.
  useEffect(() => {
    if (!open) return;

    function reposition() {
      const trigger = triggerRef.current;
      const menu = menuRef.current;
      if (!trigger || !menu) return;

      const rect = trigger.getBoundingClientRect();
      const vh = window.innerHeight;
      const spaceBelow = vh - rect.bottom;
      const openUpward = spaceBelow < 220 && rect.top > spaceBelow;

      menu.style.setProperty("--cs-left",  `${Math.round(rect.left)}px`);
      menu.style.setProperty("--cs-width", `${Math.round(rect.width)}px`);

      if (openUpward) {
        menu.style.setProperty("--cs-top",    "auto");
        menu.style.setProperty("--cs-bottom", `${Math.round(vh - rect.top + 4)}px`);
      } else {
        menu.style.setProperty("--cs-top",    `${Math.round(rect.bottom + 4)}px`);
        menu.style.setProperty("--cs-bottom", "auto");
      }
    }

    reposition();
    window.addEventListener("scroll",  reposition, { capture: true, passive: true });
    window.addEventListener("resize",  reposition,  { passive: true });
    return () => {
      window.removeEventListener("scroll",  reposition, { capture: true });
      window.removeEventListener("resize",  reposition);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const selectedIndex = options.findIndex((o) => o.value === value && !o.disabled);
    const firstEnabled  = options.findIndex((o) => !o.disabled);
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : firstEnabled);
  }, [open, options, value]);

  // Close on outside pointer-down (portal menu is outside rootRef)
  useEffect(() => {
    if (!open || typeof document === "undefined") return;
    const handlePointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  function commitOption(option: CustomSelectOption<TValue>) {
    if (option.disabled) return;
    onChange(option.value);
    setOpen(false);
    triggerRef.current?.focus();
  }

  function moveActive(delta: number) {
    if (!hasEnabledOptions) return;
    setActiveIndex((current) => {
      const start = current >= 0 ? current : 0;
      for (let offset = 1; offset <= options.length; offset++) {
        const next = (start + delta * offset + options.length) % options.length;
        if (!options[next]?.disabled) return next;
      }
      return current;
    });
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) return;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        open ? moveActive(1) : setOpen(true);
        break;
      case "ArrowUp":
        event.preventDefault();
        open ? moveActive(-1) : setOpen(true);
        break;
      case "Home": {
        event.preventDefault();
        const idx = options.findIndex((o) => !o.disabled);
        if (idx >= 0) setActiveIndex(idx);
        break;
      }
      case "End": {
        event.preventDefault();
        for (let i = options.length - 1; i >= 0; i--) {
          if (!options[i]?.disabled) { setActiveIndex(i); break; }
        }
        break;
      }
      case "Enter":
      case " ":
        event.preventDefault();
        if (!open) { setOpen(true); break; }
        if (activeOption) commitOption(activeOption);
        break;
      case "Escape":
        setOpen(false);
        break;
    }
  }

  // The menu is rendered in a portal attached to document.body so it
  // escapes every stacking context (isolation, z-index, backdrop-filter).
  // Position is applied imperatively via CSS custom properties (no inline style prop).
  const menuContent = open ? (
    <div
      id={listboxId}
      ref={setMenuRef}
      className="custom-select-menu custom-select-menu--portal"
      role="listbox"
      aria-label={ariaLabel}
      aria-activedescendant={
        activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined
      }
      onMouseDown={(e) => e.preventDefault()}
    >
      {options.map((option, index) => {
        const isSelected = option.value === value;
        const isActive   = index === activeIndex;
        return (
          <button
            id={`${listboxId}-option-${index}`}
            key={option.value || `empty-${index}`}
            type="button"
            role="option"
            aria-selected={isSelected}
            disabled={option.disabled}
            className={[
              "custom-select-option",
              isSelected ? "is-selected" : "",
              isActive   ? "is-active"   : "",
            ].filter(Boolean).join(" ")}
            onMouseEnter={() => setActiveIndex(index)}
            onPointerDown={(e) => e.preventDefault()}
            onClick={() => commitOption(option)}
          >
            <span className="custom-select-option-label">{option.label}</span>
            {option.helper ? (
              <span className="custom-select-option-helper">{option.helper}</span>
            ) : null}
            {isSelected ? <span className="custom-select-check" aria-hidden="true" /> : null}
          </button>
        );
      })}
    </div>
  ) : null;

  return (
    <div
      ref={rootRef}
      className={[
        "custom-select",
        `custom-select-${size}`,
        open     ? "is-open"    : "",
        hasSelection ? "has-value"  : "",
        disabled ? "is-disabled" : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
      onBlur={(event) => {
        const next = event.relatedTarget as Node | null;
        if (!event.currentTarget.contains(next) && !menuRef.current?.contains(next)) {
          setOpen(false);
        }
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        className="custom-select-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => { if (!disabled) setOpen((c) => !c); }}
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

      {typeof document !== "undefined"
        ? createPortal(menuContent, document.body)
        : null}
    </div>
  );
}

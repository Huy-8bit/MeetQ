import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonStyleOptions {
  variant?: ButtonVariant;
  size?: ButtonSize;
  iconOnly?: boolean;
  block?: boolean;
  className?: string;
}

export function buttonClassName({
  variant = "secondary",
  size = "md",
  iconOnly = false,
  block = false,
  className,
}: ButtonStyleOptions = {}): string {
  return [
    "btn",
    `btn--${variant}`,
    size !== "md" ? `btn--${size}` : "",
    iconOnly ? "btn--icon" : "",
    block ? "btn--block" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
}

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    Omit<ButtonStyleOptions, "className"> {
  /** Shows a spinner, disables the button and sets aria-busy. */
  loading?: boolean;
  /** Leading icon. With `iconOnly`, pass an `aria-label`. */
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant,
    size,
    iconOnly,
    block,
    loading = false,
    icon,
    className,
    disabled,
    type = "button",
    children,
    ...props
  },
  ref,
) {
  return (
    <button
      {...props}
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClassName({
        variant,
        size,
        iconOnly,
        block,
        className: [loading ? "is-loading" : "", className ?? ""].filter(Boolean).join(" "),
      })}
    >
      {loading ? <Spinner /> : icon}
      {iconOnly ? null : children}
    </button>
  );
});

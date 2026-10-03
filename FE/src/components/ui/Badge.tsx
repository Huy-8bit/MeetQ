import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

interface BadgeProps {
  tone?: BadgeTone;
  outline?: boolean;
  /** Leading status dot; meaning is always repeated by the badge text. */
  dot?: boolean;
  pulse?: boolean;
  title?: string;
  children: ReactNode;
}

export function Badge({ tone = "neutral", outline = false, dot = false, pulse = false, title, children }: BadgeProps) {
  return (
    <span
      className={[
        "badge",
        tone !== "neutral" ? `badge--${tone}` : "",
        outline ? "badge--outline" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      title={title}
    >
      {dot ? <span className={pulse ? "status-dot is-pulsing" : "status-dot"} aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

import type { ReactNode } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";

export type AlertTone = "danger" | "warning" | "info" | "success";

const ICONS = {
  danger: AlertCircle,
  warning: AlertTriangle,
  info: Info,
  success: CheckCircle2,
} as const;

export function Alert({ tone = "info", children }: { tone?: AlertTone; children: ReactNode }) {
  const Icon = ICONS[tone];
  return (
    <div className={`alert alert--${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <Icon size={16} aria-hidden="true" />
      <div className="alert-body">{children}</div>
    </div>
  );
}

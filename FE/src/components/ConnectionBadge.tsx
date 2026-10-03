import type { GatewayConnectionState } from "../types/livekit";
import { Badge, type BadgeTone } from "./ui/Badge";

interface ConnectionBadgeProps {
  state: GatewayConnectionState;
}

const STATES: Record<GatewayConnectionState, { label: string; tone: BadgeTone; pulse?: boolean }> = {
  idle: { label: "Idle", tone: "neutral" },
  connecting: { label: "Connecting", tone: "warning", pulse: true },
  connected: { label: "Connected", tone: "success" },
  reconnecting: { label: "Reconnecting", tone: "warning", pulse: true },
  disconnected: { label: "Disconnected", tone: "danger" },
};

export function ConnectionBadge({ state }: ConnectionBadgeProps) {
  const { label, tone, pulse } = STATES[state];
  return (
    <span className="connection-badge" role="status" aria-live="polite">
      <Badge tone={tone} dot pulse={pulse}>
        {label}
      </Badge>
    </span>
  );
}

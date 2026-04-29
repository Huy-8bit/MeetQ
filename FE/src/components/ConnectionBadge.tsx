import type { GatewayConnectionState } from "../types/livekit";

interface ConnectionBadgeProps {
  state: GatewayConnectionState;
}

const LABELS: Record<GatewayConnectionState, string> = {
  idle: "Idle",
  connecting: "Connecting",
  connected: "Connected",
  reconnecting: "Reconnecting",
  disconnected: "Disconnected",
};

export function ConnectionBadge({ state }: ConnectionBadgeProps) {
  return (
    <div className={`connection-badge connection-${state}`}>
      <span className="connection-dot" />
      <span>{LABELS[state]}</span>
    </div>
  );
}

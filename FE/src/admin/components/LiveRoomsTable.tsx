import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { LiveRoomRow } from "../api/types";
import { AI_MODE_LABELS, formatClock, formatTimeLeft, languageList } from "../lib/format";
import { DataTable, type Column } from "./DataTable";
import { AiStateBadge, RoomStatusBadge } from "./StatusBadges";

export const liveRoomHref = (roomId: string) => `/admin/live-rooms/${encodeURIComponent(roomId)}`;

const COLUMNS: Array<Column<LiveRoomRow>> = [
  {
    key: "room",
    header: "Room",
    render: (row) => (
      <Link className="adm-mono-link" to={liveRoomHref(row.room_id)}>
        {row.room_id}
      </Link>
    ),
  },
  { key: "languages", header: "Languages", render: (row) => languageList(row.room_languages) },
  {
    key: "participants",
    header: "Participants",
    align: "right",
    render: (row) => (
      <span title={`${row.participants_online} online of ${row.participants_total} joined`}>
        {row.participants_online}
        {row.participants_total > row.participants_online ? <span className="text-tertiary"> / {row.participants_total}</span> : null}
      </span>
    ),
  },
  { key: "mode", header: "AI mode", render: (row) => AI_MODE_LABELS[row.ai_mode], hideOnNarrow: true },
  {
    key: "state",
    header: "BRSE state",
    render: (row) => (
      <span className="adm-cell-stack">
        <AiStateBadge state={row.brse_state} />
        {row.runtime_attached === false ? <span className="adm-cell-warning">Runtime not attached</span> : null}
      </span>
    ),
  },
  { key: "created", header: "Created", render: (row) => formatClock(row.created_at), hideOnNarrow: true },
  {
    key: "left",
    header: "Time left",
    align: "right",
    render: (row) => (
      <span className={row.seconds_left !== null && row.seconds_left < 300 ? "adm-text-warning" : undefined}>
        {formatTimeLeft(row.seconds_left)}
      </span>
    ),
  },
  {
    key: "status",
    header: "Status",
    render: (row) => (
      <span className="adm-cell-stack">
        <RoomStatusBadge status={row.status} />
        {row.recent_error_count > 0 ? <span className="adm-cell-warning">{row.recent_error_count} error(s) / 10 min</span> : null}
      </span>
    ),
  },
];

// Narrow layouts (the Overview side-by-side grid) drop the secondary columns.
const COMPACT_KEYS = new Set(["room", "languages", "participants", "state", "left", "status"]);
const COMPACT_COLUMNS = COLUMNS.filter((column) => COMPACT_KEYS.has(column.key));

export function LiveRoomsTable({
  rows,
  empty,
  busy,
  compact = false,
}: {
  rows: LiveRoomRow[];
  empty: ReactNode;
  busy?: boolean;
  compact?: boolean;
}) {
  return (
    <DataTable
      caption="Live rooms"
      columns={compact ? COMPACT_COLUMNS : COLUMNS}
      rows={rows}
      getRowKey={(row) => row.room_id}
      getRowHref={(row) => liveRoomHref(row.room_id)}
      empty={empty}
      busy={busy}
    />
  );
}

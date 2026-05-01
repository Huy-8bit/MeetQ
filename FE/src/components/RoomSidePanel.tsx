import type { ReactNode } from "react";

export type RoomPanelTab = "relay" | "chat" | "people";

interface RoomSidePanelProps {
  activeTab: RoomPanelTab;
  transcriptCount: number;
  chatCount: number;
  participantCount: number;
  onTabChange: (tab: RoomPanelTab) => void;
  relay: ReactNode;
  chat: ReactNode;
  people: ReactNode;
}

const TAB_LABELS: Record<RoomPanelTab, string> = {
  relay: "Relay",
  chat: "Chat",
  people: "People",
};

export function RoomSidePanel({
  activeTab,
  transcriptCount,
  chatCount,
  participantCount,
  onTabChange,
  relay,
  chat,
  people,
}: RoomSidePanelProps) {
  const counts: Record<RoomPanelTab, number | null> = {
    relay: transcriptCount,
    chat: chatCount,
    people: participantCount,
  };

  const content: Record<RoomPanelTab, ReactNode> = {
    relay,
    chat,
    people,
  };

  return (
    <aside className="room-side-panel">
      <div className="room-side-tabs" role="tablist" aria-label="Room panels">
        {(Object.keys(TAB_LABELS) as RoomPanelTab[]).map((tab) => (
          <button
            aria-selected={activeTab === tab}
            className={activeTab === tab ? "room-side-tab is-active" : "room-side-tab"}
            key={tab}
            role="tab"
            type="button"
            onClick={() => onTabChange(tab)}
          >
            <span>{TAB_LABELS[tab]}</span>
            {counts[tab] !== null ? <strong>{counts[tab]}</strong> : null}
          </button>
        ))}
      </div>

      <div className="room-side-content" role="tabpanel">
        {content[activeTab]}
      </div>
    </aside>
  );
}

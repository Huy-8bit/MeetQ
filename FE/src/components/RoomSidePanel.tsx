import type { ReactNode } from "react";

export type RoomPanelTab = "relay" | "chat" | "summary" | "people";

interface RoomSidePanelProps {
  open: boolean;
  onClose: () => void;
  activeTab: RoomPanelTab;
  transcriptCount: number;
  chatCount: number;
  summaryCount?: number;
  participantCount: number;
  onTabChange: (tab: RoomPanelTab) => void;
  relay: ReactNode;
  chat: ReactNode;
  summary: ReactNode;
  people: ReactNode;
}

const TABS: { id: RoomPanelTab; label: string }[] = [
  { id: "relay", label: "Relay" },
  { id: "chat", label: "Chat" },
  { id: "summary", label: "Summary" },
  { id: "people", label: "People" },
];

export function RoomSidePanel({
  open,
  onClose,
  activeTab,
  transcriptCount,
  chatCount,
  summaryCount = 0,
  participantCount,
  onTabChange,
  relay,
  chat,
  summary,
  people,
}: RoomSidePanelProps) {
  const counts: Record<RoomPanelTab, number> = {
    relay: transcriptCount,
    chat: chatCount,
    summary: summaryCount,
    people: participantCount,
  };

  const content: Record<RoomPanelTab, ReactNode> = { relay, chat, summary, people };

  return (
    <aside className={open ? "room-side-panel is-open" : "room-side-panel"} aria-hidden={open ? undefined : true}>
      <div className="side-panel-header">
        <nav className="side-panel-tabs" role="tablist" aria-label="Room panels">
          {TABS.map(({ id, label }) => {
            const count = counts[id];
            return (
              <button
                key={id}
                role="tab"
                type="button"
                aria-selected={activeTab === id ? true : false}
                className={activeTab === id ? "side-tab is-active" : "side-tab"}
                onClick={() => onTabChange(id)}
              >
                {label}
                {count > 0 ? <span className="side-tab-badge">{count}</span> : null}
              </button>
            );
          })}
        </nav>

        <button
          className="side-panel-close"
          type="button"
          aria-label="Close panel"
          onClick={onClose}
        >
          ✕
        </button>
      </div>

      <div className={`side-panel-body side-panel-body-${activeTab}`} role="tabpanel">
        {content[activeTab]}
      </div>
    </aside>
  );
}

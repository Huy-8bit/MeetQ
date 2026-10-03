import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "./ui/Button";

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
  participantCount,
  onTabChange,
  relay,
  chat,
  summary,
  people,
}: RoomSidePanelProps) {
  const tabRefs = useRef<Record<RoomPanelTab, HTMLButtonElement | null>>({
    relay: null,
    chat: null,
    summary: null,
    people: null,
  });
  // Summary is a single document, so a count badge adds nothing there.
  const counts: Partial<Record<RoomPanelTab, number>> = {
    relay: transcriptCount,
    chat: chatCount,
    people: participantCount,
  };
  const content: Record<RoomPanelTab, ReactNode> = { relay, chat, summary, people };

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    const next = TABS[(index + delta + TABS.length) % TABS.length].id;
    onTabChange(next);
    tabRefs.current[next]?.focus();
  }

  // Stays mounted while hidden so an unsent chat draft survives closing the panel.
  return (
    <aside className="side-panel" aria-label="Meeting side panel" hidden={!open}>
      <div className="side-panel-header">
        <div className="tabs" role="tablist" aria-label="Side panel sections">
          {TABS.map(({ id, label }, index) => {
            const count = counts[id] ?? 0;
            const selected = activeTab === id;
            return (
              <button
                key={id}
                ref={(node) => {
                  tabRefs.current[id] = node;
                }}
                id={`side-tab-${id}`}
                role="tab"
                type="button"
                className="tab"
                aria-selected={selected}
                aria-controls="side-panel-body"
                tabIndex={selected ? 0 : -1}
                onClick={() => onTabChange(id)}
                onKeyDown={(event) => handleTabKeyDown(event, index)}
              >
                {label}
                {count > 0 ? <span className="tab-count">{count}</span> : null}
              </button>
            );
          })}
        </div>
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          icon={<X size={16} />}
          aria-label="Close side panel"
          onClick={onClose}
        />
      </div>

      <div
        id="side-panel-body"
        className={`side-panel-body side-panel-body--${activeTab}`}
        role="tabpanel"
        aria-labelledby={`side-tab-${activeTab}`}
      >
        {content[activeTab]}
      </div>
    </aside>
  );
}

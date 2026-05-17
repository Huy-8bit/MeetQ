import type { ReactNode } from "react";
import { PanelRightClose } from "lucide-react";
import {
  useContentSwitchMotion,
  usePanelTransition,
} from "../lib/motion";
import { useTextAnimations } from "../lib/textAnimations";
import { MotionButton } from "./MotionButton";

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

const TABS: { id: RoomPanelTab; label: string; detail: string }[] = [
  { id: "relay", label: "Relay", detail: "Live transcript and BRSE output" },
  { id: "chat", label: "Chat", detail: "Room messages" },
  { id: "summary", label: "Summary", detail: "Meeting notes and actions" },
  { id: "people", label: "People", detail: "Participants and AI relay presence" },
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
  const panelMotionRef = usePanelTransition<HTMLElement>(open, {
    axis: "x",
    distance: 20,
  });
  useTextAnimations(panelMotionRef, {
    selector: ".side-panel-header [data-text-animate]",
    dependencies: [activeTab, open],
  });
  const bodyMotionRef = useContentSwitchMotion<HTMLDivElement>(activeTab, {
    selector: ":scope > *",
    distance: 8,
    stagger: 0,
  });
  const counts: Record<RoomPanelTab, number> = {
    relay: transcriptCount,
    chat: chatCount,
    summary: summaryCount,
    people: participantCount,
  };

  const content: Record<RoomPanelTab, ReactNode> = { relay, chat, summary, people };
  const activeTabCopy = TABS.find((tab) => tab.id === activeTab) ?? TABS[0];

  return (
    <aside
      ref={panelMotionRef}
      className={open ? "room-side-panel is-open" : "room-side-panel"}
      aria-label="Meeting context panel"
      aria-hidden={open ? undefined : true}
    >
      <div className="side-panel-header">
        <div className="side-panel-heading">
          <span className="side-panel-kicker" data-text-animate="highlight">Context</span>
          <div>
            <strong className="side-panel-title" data-text-animate="fade">{activeTabCopy.label}</strong>
            <p className="side-panel-subtitle" data-text-animate="fade">{activeTabCopy.detail}</p>
          </div>
        </div>

        <MotionButton
          className="side-panel-mobile-dismiss"
          type="button"
          aria-label="Hide context panel"
          onClick={onClose}
        >
          <PanelRightClose size={16} />
          <span>Hide</span>
        </MotionButton>

        <nav className="side-panel-tabs" role="tablist" aria-label="Room panels">
          {TABS.map(({ id, label }) => {
            const count = counts[id];
            return (
              <MotionButton
                key={id}
                role="tab"
                type="button"
                aria-selected={activeTab === id ? true : false}
                className={activeTab === id ? "side-tab is-active" : "side-tab"}
                onClick={() => onTabChange(id)}
              >
                <span className="side-tab-label" data-text-animate="cta">{label}</span>
                {count > 0 ? <span className="side-tab-badge">{count}</span> : null}
              </MotionButton>
            );
          })}
        </nav>
      </div>

      <div
        ref={bodyMotionRef}
        className={`side-panel-body side-panel-body-${activeTab}`}
        role="tabpanel"
      >
        {content[activeTab]}
      </div>
    </aside>
  );
}

import type { AppThemeMode, RoomLayoutMode } from "../lib/uiPreferences";
import { MotionButton } from "./MotionButton";

interface MeetingViewPanelProps {
  themeMode: AppThemeMode;
  layoutMode: RoomLayoutMode;
  onThemeChange: (theme: AppThemeMode) => void;
  onLayoutChange: (layout: RoomLayoutMode) => void;
}

const THEME_OPTIONS: Array<{ value: AppThemeMode; label: string }> = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const LAYOUT_OPTIONS: Array<{ value: RoomLayoutMode; label: string; helper: string }> = [
  {
    value: "stage-focus",
    label: "Wide stage",
    helper: "More space for video and shared screen.",
  },
  {
    value: "balanced",
    label: "Balanced",
    helper: "Keep stage and panels evenly weighted.",
  },
  {
    value: "compact",
    label: "Compact panel",
    helper: "Give the panel a tighter working width.",
  },
];

export function MeetingViewPanel({
  themeMode,
  layoutMode,
  onThemeChange,
  onLayoutChange,
}: MeetingViewPanelProps) {
  return (
    <section className="meeting-view-panel panel-section" aria-labelledby="meeting-view-title">
      <div className="panel-header compact">
        <h3 id="meeting-view-title" data-text-animate="fade">View</h3>
        <p data-text-animate="fade">Theme and room layout.</p>
      </div>

      <div className="view-setting-block">
        <div className="view-setting-label">
          <strong data-text-animate="fade">Theme</strong>
          <span data-text-animate="fade">Choose the meeting color mode.</span>
        </div>
        <div className="segmented-control" role="group" aria-label="Theme mode">
          {THEME_OPTIONS.map((option) => (
            <MotionButton
              key={option.value}
              className={themeMode === option.value ? "is-active" : ""}
              type="button"
              onClick={() => onThemeChange(option.value)}
              aria-pressed={themeMode === option.value}
              data-text-animate="cta"
            >
              {option.label}
            </MotionButton>
          ))}
        </div>
      </div>

      <div className="view-setting-block">
        <div className="view-setting-label">
          <strong data-text-animate="fade">Layout</strong>
          <span data-text-animate="fade">Adjust the meeting room balance.</span>
        </div>
        <div className="layout-option-grid" role="group" aria-label="Meeting layout">
          {LAYOUT_OPTIONS.map((option) => (
            <MotionButton
              key={option.value}
              className={layoutMode === option.value ? "layout-option is-active" : "layout-option"}
              type="button"
              onClick={() => onLayoutChange(option.value)}
              aria-pressed={layoutMode === option.value}
              data-text-animate="cta"
            >
              <strong>{option.label}</strong>
              <span>{option.helper}</span>
            </MotionButton>
          ))}
        </div>
      </div>
    </section>
  );
}

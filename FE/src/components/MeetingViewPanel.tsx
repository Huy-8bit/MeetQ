import type { AppThemeMode, RoomLayoutMode } from "../lib/uiPreferences";

interface MeetingViewPanelProps {
  themeMode: AppThemeMode;
  layoutMode: RoomLayoutMode;
  stageFocusActive: boolean;
  onThemeChange: (theme: AppThemeMode) => void;
  onLayoutChange: (layout: RoomLayoutMode) => void;
  onToggleStageFocus: () => void;
}

const THEME_OPTIONS: Array<{ value: AppThemeMode; label: string }> = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const LAYOUT_OPTIONS: Array<{ value: RoomLayoutMode; label: string; helper: string }> = [
  {
    value: "stage-focus",
    label: "Stage focus",
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
  stageFocusActive,
  onThemeChange,
  onLayoutChange,
  onToggleStageFocus,
}: MeetingViewPanelProps) {
  return (
    <section className="meeting-view-panel panel-section" aria-labelledby="meeting-view-title">
      <div className="panel-header compact">
        <h3 id="meeting-view-title">View</h3>
        <p>Theme, room layout, and stage focus.</p>
      </div>

      <div className="view-setting-block">
        <div className="view-setting-label">
          <strong>Theme</strong>
          <span>Choose the meeting color mode.</span>
        </div>
        <div className="segmented-control" role="group" aria-label="Theme mode">
          {THEME_OPTIONS.map((option) => (
            <button
              key={option.value}
              className={themeMode === option.value ? "is-active" : ""}
              type="button"
              onClick={() => onThemeChange(option.value)}
              aria-pressed={themeMode === option.value}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="view-setting-block">
        <div className="view-setting-label">
          <strong>Layout</strong>
          <span>Adjust the meeting room balance.</span>
        </div>
        <div className="layout-option-grid" role="group" aria-label="Meeting layout">
          {LAYOUT_OPTIONS.map((option) => (
            <button
              key={option.value}
              className={layoutMode === option.value ? "layout-option is-active" : "layout-option"}
              type="button"
              onClick={() => onLayoutChange(option.value)}
              aria-pressed={layoutMode === option.value}
            >
              <strong>{option.label}</strong>
              <span>{option.helper}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="view-setting-block focus-setting-block">
        <div className="view-setting-label">
          <strong>Stage focus</strong>
          <span>Hide the side panel and enlarge meeting content.</span>
        </div>
        <button
          className={stageFocusActive ? "button-secondary focus-toggle is-active" : "button-secondary focus-toggle"}
          type="button"
          onClick={onToggleStageFocus}
        >
          {stageFocusActive ? "Exit focus" : "Focus stage"}
        </button>
      </div>
    </section>
  );
}

import type { AppThemeMode, RoomLayoutMode } from "../lib/uiPreferences";
import { Field } from "./ui/Field";
import { SegmentedControl } from "./ui/SegmentedControl";

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
    helper: "More space for video and shared screens.",
  },
  {
    value: "balanced",
    label: "Balanced",
    helper: "Stage and side panel share the space evenly.",
  },
  {
    value: "compact",
    label: "Compact",
    helper: "A narrower side panel.",
  },
];

export function MeetingViewPanel({
  themeMode,
  layoutMode,
  onThemeChange,
  onLayoutChange,
}: MeetingViewPanelProps) {
  const layoutHelper = LAYOUT_OPTIONS.find((option) => option.value === layoutMode)?.helper;

  return (
    <section className="drawer-section" aria-labelledby="view-settings-title">
      <div className="drawer-section-header">
        <h3 className="section-title" id="view-settings-title">View</h3>
      </div>

      <div className="drawer-section-body">
        <Field asGroup labelId="theme-mode-label" label="Theme">
          <SegmentedControl
            ariaLabelledBy="theme-mode-label"
            value={themeMode}
            options={THEME_OPTIONS}
            onChange={onThemeChange}
          />
        </Field>

        <Field asGroup labelId="layout-mode-label" label="Layout" helper={layoutHelper}>
          <SegmentedControl
            ariaLabelledBy="layout-mode-label"
            value={layoutMode}
            options={LAYOUT_OPTIONS.map(({ value, label }) => ({ value, label }))}
            onChange={onLayoutChange}
          />
        </Field>
      </div>
    </section>
  );
}

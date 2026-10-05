import { useEffect, useId, useRef, useState } from "react";
import type { ScreenShareQuality } from "../lib/livekit";
import {
  loadScreenShareQualityPreference,
  saveScreenShareQualityPreference,
} from "../lib/uiPreferences";
import { Button } from "./ui/Button";

export interface ScreenShareChoice {
  quality: ScreenShareQuality;
  includeAudio: boolean;
}

const QUALITY_OPTIONS: Array<{
  value: ScreenShareQuality;
  label: string;
  spec: string;
  detail: string;
}> = [
  {
    value: "detail",
    label: "High quality",
    spec: "1080p · 30 FPS",
    detail: "Best for text, slides, and coding.",
  },
  {
    value: "motion",
    label: "Smooth motion",
    spec: "1080p · Up to 60 FPS",
    detail: "Best for video and animations.",
  },
];

interface ScreenShareDialogProps {
  open: boolean;
  /**
   * Called synchronously from the confirm click so the caller can start
   * getDisplayMedia while the browser still has the user activation.
   */
  onConfirm: (choice: ScreenShareChoice) => void;
  onCancel: () => void;
}

/** Pick capture quality and shared audio before the browser's screen picker opens. */
export function ScreenShareDialog({ open, onConfirm, onCancel }: ScreenShareDialogProps) {
  const titleId = useId();
  const audioHelpId = useId();
  const firstFocusRef = useRef<HTMLInputElement | null>(null);
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;
  const [quality, setQuality] = useState<ScreenShareQuality>(loadScreenShareQualityPreference);
  const [includeAudio, setIncludeAudio] = useState(false);

  useEffect(() => {
    if (!open) return;
    setQuality(loadScreenShareQualityPreference());
    setIncludeAudio(false);
    const previouslyFocused = document.activeElement as HTMLElement | null;
    firstFocusRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancelRef.current();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  const handleConfirm = () => {
    saveScreenShareQualityPreference(quality);
    onConfirm({ quality, includeAudio });
  };

  return (
    <div className="dialog-layer">
      <div className="dialog-backdrop" onClick={onCancel} aria-hidden="true" />
      <div className="dialog card" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="card-body dialog-body">
          <h2 className="card-title" id={titleId}>
            Share screen
          </h2>

          <fieldset className="share-quality">
            <legend className="field-label">Quality</legend>
            {QUALITY_OPTIONS.map((option) => (
              <label
                key={option.value}
                className={`share-quality-option${quality === option.value ? " is-selected" : ""}`}
              >
                <input
                  ref={(node) => {
                    if (option.value === quality) firstFocusRef.current = node;
                  }}
                  type="radio"
                  name="screen-share-quality"
                  value={option.value}
                  checked={quality === option.value}
                  onChange={() => setQuality(option.value)}
                />
                <span className="share-quality-text">
                  <span className="share-quality-title">
                    {option.label} <span className="share-quality-spec">— {option.spec}</span>
                  </span>
                  <span className="share-quality-detail">{option.detail}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div className="share-audio">
            <label className="share-audio-option">
              <input
                type="checkbox"
                checked={includeAudio}
                onChange={(event) => setIncludeAudio(event.target.checked)}
                aria-describedby={audioHelpId}
              />
              <span>Include shared audio</span>
            </label>
            <p className="field-helper" id={audioHelpId}>
              Works best when sharing a Chrome or Edge tab. Shared audio is heard by
              participants but isn&apos;t sent to the AI interpreter.
            </p>
          </div>

          <div className="dialog-actions">
            <Button variant="secondary" onClick={onCancel}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleConfirm}>
              Share
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

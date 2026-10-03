interface MicLevelMeterProps {
  /** 0–1 normalised RMS level */
  level: number;
  /** 0–1 normalised peak level */
  peak?: number;
  /** Optional dB label from server */
  db?: number | null;
}

const BAR_COUNT = 20;

export function MicLevelMeter({ level, peak = 0, db = null }: MicLevelMeterProps) {
  const activeBars = Math.round(level * BAR_COUNT);
  const peakBar = Math.round(peak * BAR_COUNT);

  return (
    <div className="mic-level-meter" role="meter" aria-label="Microphone level" aria-valuenow={Math.round(level * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div className="mic-level-bars">
        {Array.from({ length: BAR_COUNT }, (_, i) => {
          const barIndex = i + 1;
          const isActive = barIndex <= activeBars;
          const isPeak = barIndex === peakBar && peak > 0;
          const isHigh = barIndex > BAR_COUNT * 0.75;
          const isMid = barIndex > BAR_COUNT * 0.45 && !isHigh;

          let className = "mic-bar";
          if (isPeak) className += " mic-bar-peak";
          else if (isActive && isHigh) className += " mic-bar-high";
          else if (isActive && isMid) className += " mic-bar-mid";
          else if (isActive) className += " mic-bar-low";

          return <span key={i} className={className} />;
        })}
      </div>
      {db !== null ? (
        <span className="mic-level-db">{db.toFixed(1)} dB</span>
      ) : (
        <span className="mic-level-db">{Math.round(level * 100)}%</span>
      )}
    </div>
  );
}

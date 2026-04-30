import { useRef } from "react";
import { Link } from "react-router-dom";
import { MicLevelMeter } from "../components/MicLevelMeter";
import { useMicTest } from "../features/test/useMicTest";
import { useTranslationTest } from "../features/test/useTranslationTest";
import type { Language } from "../types/api";

const LANGUAGES: { value: Language; label: string }[] = [
  { value: "vi", label: "Tiếng Việt (VI)" },
  { value: "en", label: "English (EN)" },
  { value: "ja", label: "日本語 (JA)" },
];

export function TestPage() {
  return (
    <main className="test-page">
      <header className="test-page-header">
        <div>
          <span className="eyebrow">Dev Tools</span>
          <h1>Mic &amp; Translation Test</h1>
          <p>
            Kiểm tra mic và dịch thuật trước khi vào phòng họp thật.
          </p>
        </div>
        <Link to="/" className="button-secondary test-back-btn">
          ← Về Trang Chủ
        </Link>
      </header>

      <div className="test-sections">
        <MicTestSection />
        <TranslationTestSection />
      </div>
    </main>
  );
}

// ─── Mic Test ─────────────────────────────────────────────────────────────────

function MicTestSection() {
  const { state, start, stop } = useMicTest();
  const isActive =
    state.status === "active" || state.status === "silence" || state.status === "connecting";

  return (
    <section className="test-card panel">
      <div className="test-card-header">
        <div>
          <h2>Mic Test</h2>
          <p>Kiểm tra microphone có hoạt động và backend nhận audio chưa.</p>
        </div>
        <span className={`test-status-badge status-${state.status}`}>
          {statusLabel(state.status)}
        </span>
      </div>

      {state.error ? (
        <div className="banner banner-danger test-error">{state.error}</div>
      ) : null}

      <div className="mic-level-section">
        <MicLevelMeter level={state.level} peak={state.peak} db={state.db} />
        <div className="mic-feedback">
          {micFeedbackText(state.status, state.level)}
        </div>
      </div>

      {state.sessionId ? (
        <p className="test-session-id">Session: {state.sessionId}</p>
      ) : null}

      <div className="test-controls">
        {!isActive ? (
          <button
            className="button-primary"
            onClick={() => void start()}
            disabled={state.status === "requesting_permission" || state.status === "connecting"}
          >
            {state.status === "requesting_permission"
              ? "Đang xin quyền mic..."
              : state.status === "connecting"
              ? "Đang kết nối..."
              : "Bắt đầu Mic Test"}
          </button>
        ) : (
          <button className="button-danger" onClick={() => void stop()}>
            Dừng
          </button>
        )}
      </div>
    </section>
  );
}

function micFeedbackText(status: string, level: number): string {
  switch (status) {
    case "idle":
      return "Nhấn bắt đầu để kiểm tra mic.";
    case "requesting_permission":
      return "Đang xin quyền truy cập microphone...";
    case "connecting":
      return "Đang kết nối đến backend test session...";
    case "active":
      return level > 0.05 ? "Đang nhận âm thanh" : "Đang chờ tiếng nói...";
    case "silence":
      return "Không phát hiện tiếng nói (im lặng)";
    case "stopped":
      return "Đã dừng mic test.";
    case "error":
      return "Đã xảy ra lỗi. Xem chi tiết bên trên.";
    default:
      return "";
  }
}

// ─── Translation Test ─────────────────────────────────────────────────────────

function TranslationTestSection() {
  const { state, start, stop, setSrcLang, setTgtLang } = useTranslationTest("vi", "en");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const isRunning =
    state.status === "listening" ||
    state.status === "translating" ||
    state.status === "connecting";

  const canChangeLang = state.status === "idle" || state.status === "stopped";

  function handleStart() {
    void start(state.srcLang, state.tgtLang);
  }

  // Play audio if backend provides a URL
  function playAudio(url: string) {
    if (!audioRef.current) return;
    audioRef.current.src = url;
    void audioRef.current.play().catch(() => undefined);
  }

  // Trigger playback when a new audio URL arrives
  const prevAudioUrlRef = useRef<string | null>(null);
  if (
    state.lastAudioUrl &&
    state.lastAudioUrl !== prevAudioUrlRef.current
  ) {
    prevAudioUrlRef.current = state.lastAudioUrl;
    playAudio(state.lastAudioUrl);
  }

  return (
    <section className="test-card panel">
      <div className="test-card-header">
        <div>
          <h2>Translation Test</h2>
          <p>Nói thử và xem kết quả dịch realtime từ backend.</p>
        </div>
        <span className={`test-status-badge status-${state.status}`}>
          {translationStatusLabel(state.status)}
        </span>
      </div>

      {state.error ? (
        <div className="banner banner-danger test-error">{state.error}</div>
      ) : null}

      <div className="translation-lang-row">
        <label className="compact-field">
          <span>Ngôn ngữ nguồn</span>
          <select
            value={state.srcLang}
            disabled={!canChangeLang}
            onChange={(e) => setSrcLang(e.target.value as Language)}
          >
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>

        <span className="lang-arrow">→</span>

        <label className="compact-field">
          <span>Ngôn ngữ đích</span>
          <select
            value={state.tgtLang}
            disabled={!canChangeLang}
            onChange={(e) => setTgtLang(e.target.value as Language)}
          >
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {state.sessionId ? (
        <p className="test-session-id">Session: {state.sessionId}</p>
      ) : null}

      <div className="translation-panels">
        <div className="translation-text-box">
          <span className="translation-box-label">
            Lời gốc ({state.srcLang.toUpperCase()})
          </span>
          <div className="translation-text-content">
            {state.items.length === 0 ? (
              <span className="translation-placeholder">
                {isRunning ? "Đang chờ tiếng nói..." : "Chưa có dữ liệu"}
              </span>
            ) : (
              state.items.map((item) => (
                <p
                  key={item.id}
                  className={`translation-item-text ${item.isFinal ? "" : "is-partial"}`}
                >
                  {item.sourceText}
                  {!item.isFinal ? (
                    <span className="translation-partial-badge">…</span>
                  ) : null}
                </p>
              ))
            )}
          </div>
        </div>

        <div className="translation-text-box translation-text-box-right">
          <span className="translation-box-label">
            Bản dịch ({state.tgtLang.toUpperCase()})
            {state.status === "translating" ? (
              <span className="badge live translation-live-badge">Đang dịch</span>
            ) : null}
          </span>
          <div className="translation-text-content">
            {state.items.length === 0 ? (
              <span className="translation-placeholder">
                {isRunning ? "Đang chờ bản dịch..." : "Chưa có dữ liệu"}
              </span>
            ) : (
              state.items.map((item) => (
                <p
                  key={item.id}
                  className={`translation-item-text ${item.isFinal ? "" : "is-partial"}`}
                >
                  {item.translatedText || (
                    <span className="translation-placeholder">...</span>
                  )}
                </p>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Hidden audio element for translated audio playback */}
      <audio ref={audioRef} style={{ display: "none" }} />

      <div className="test-controls">
        {!isRunning ? (
          <button
            className="button-primary"
            onClick={handleStart}
            disabled={
              state.status === "requesting_permission" ||
              state.status === "connecting" ||
              state.srcLang === state.tgtLang
            }
          >
            {state.status === "requesting_permission"
              ? "Đang xin quyền mic..."
              : state.status === "connecting"
              ? "Đang kết nối..."
              : "Bắt đầu Translation Test"}
          </button>
        ) : (
          <button className="button-danger" onClick={() => void stop()}>
            Dừng
          </button>
        )}
        {state.srcLang === state.tgtLang && canChangeLang ? (
          <p className="inline-error" style={{ marginTop: 8 }}>
            Ngôn ngữ nguồn và đích không được trùng nhau.
          </p>
        ) : null}
      </div>
    </section>
  );
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    idle: "Chờ",
    requesting_permission: "Xin quyền",
    connecting: "Kết nối",
    active: "Đang chạy",
    silence: "Im lặng",
    stopped: "Đã dừng",
    error: "Lỗi",
  };
  return map[status] ?? status;
}

function translationStatusLabel(status: string): string {
  const map: Record<string, string> = {
    idle: "Chờ",
    requesting_permission: "Xin quyền",
    connecting: "Kết nối",
    listening: "Đang nghe",
    translating: "Đang dịch",
    stopped: "Đã dừng",
    error: "Lỗi",
  };
  return map[status] ?? status;
}

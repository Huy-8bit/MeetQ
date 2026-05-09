import { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "motion/react";
import { Zap, Mic2, CheckCircle2, Globe2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import {
  BRSE_CREATE_MODE_OPTIONS,
  buildCreateBrsePayload,
  type BrseCreateMode,
} from "../lib/brseModes";
import {
  getLanguageLabel,
  isMeetingLanguage,
  SUPPORTED_MEETING_LANGUAGES,
} from "../lib/languages";
import { extractRoomId } from "../lib/rooms";
import type { MeetingLanguage } from "../types/api";
import { CustomSelect, type CustomSelectOption } from "../components/CustomSelect";

// ─── Intro slideshow ─────────────────────────────────────────────────────────

type Slide = "chaos" | "clarity" | "translation" | "global";

const SLIDES: Slide[] = ["chaos", "clarity", "translation", "global"];
const SLIDE_DURATION = 6000; // ms each
const CREATE_BRSE_MODE_STORAGE_KEY = "meetq:create-brse-mode";

const CHAOS_TEXTS = [
  "Hello? Can you hear me?",
  "Subtitle dịch sai thuật ngữ rồi...",
  "誰か説明できますか？",
  "Can someone translate this?",
  "意味がちょっと違います...",
  "Ý của họ là gì vậy?",
  "会話についていけないです",
  "The translation feels wrong",
  "専門用語の翻訳が違います",
  "Không ai hiểu đang nói gì...",
  "Communication is breaking again...",
  "Dịch bị lệch context rồi",
  "これは本当に正しい翻訳ですか？",
  "We are losing time because of translation",
  "Can we switch back to English?",
  "会議が止まってしまった...",
  "Không follow kịp cuộc họp...",
];

const TRANSLATION_STEPS = [
  {
    vi: "Xin chào, tôi rất hân hạnh được giới thiệu về meetQ.",
    en: "Hello, I am honored to introduce meetQ.",
    jp: "こんにちは、meetQをご紹介できて光栄です。",
  },
  {
    vi: "Công nghệ này sẽ thay đổi cách chúng ta giao tiếp.",
    en: "This technology will change how we communicate.",
    jp: "この技術は私たちのコミュニケーション方法を変えます。",
  },
];

function ChaosSlide() {
  const [textIdx, setTextIdx] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTextIdx((i) => (i + 1) % CHAOS_TEXTS.length), 900);
    return () => clearInterval(id);
  }, []);

  return (
    <motion.div
      key="chaos"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.6 }}
      className="intro-slide intro-slide-chaos"
    >
      <div className="intro-chaos-grid">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="intro-tile">
            <img
              src={`https://picsum.photos/seed/${i + 20}/300/220?grayscale&blur=2`}
              alt=""
              className="intro-tile-img"
            />
            <div className="intro-tile-overlay" />
            <span className="intro-tile-badge">USER_{i} · UNDERSTAND</span>
          </div>
        ))}
      </div>

      <div className="intro-chaos-caption">
        <AnimatePresence mode="wait">
          <motion.p
            key={textIdx}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.25 }}
            className="intro-glitch-text"
            data-text={CHAOS_TEXTS[textIdx]}
          >
            {CHAOS_TEXTS[textIdx]}
          </motion.p>
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

function ClaritySlide() {
  return (
    <motion.div
      key="clarity"
      initial={{ opacity: 0, scale: 1.04 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.7 }}
      className="intro-slide intro-slide-clarity"
    >
      <div className="intro-clarity-inner">
        <motion.div
          initial={{ y: 16, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="intro-clarity-badge"
        >
          <Zap size={13} />
          AI RECONSTRUCTION ACTIVE
        </motion.div>
        <motion.h2
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.7 }}
          className="intro-clarity-headline"
        >
          Purity in <span>every word.</span>
        </motion.h2>
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1 }}
          className="intro-clarity-sub"
        >
          Zero noise. Zero delay. Absolute understanding.
        </motion.p>

        <div className="intro-clarity-bars">
          {[0.1, 0.3, 0.2].map((delay, i) => (
            <div key={i} className="intro-bar-track">
              <motion.div
                animate={{ height: ["20%", "90%", "40%", "70%"] }}
                transition={{ duration: 1.4, repeat: Infinity, delay }}
                className="intro-bar-fill"
              />
            </div>
          ))}
          <div className="intro-clarity-mic">
            <Mic2 size={14} />
            <div>
              <span className="intro-mic-label">Input</span>
              <span className="intro-mic-lang">Vietnamese (Detected)</span>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function TranslationSlide() {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setTimeout(() => setStep(1), 3000);
    return () => clearTimeout(id);
  }, []);

  const s = TRANSLATION_STEPS[step];

  return (
    <motion.div
      key="translation"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.6 }}
      className="intro-slide intro-slide-translation"
    >
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ x: 14, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: -14, opacity: 0 }}
          transition={{ duration: 0.4 }}
          className="intro-translation-card"
        >
          <div className="intro-tr-original">
            <span className="intro-tr-label">Original · VI</span>
            <p className="intro-tr-original-text">"{s.vi}"</p>
          </div>

          <div className="intro-tr-translations">
            {[
              { code: "EN", text: s.en, cls: "intro-tr-badge-en" },
              { code: "JP", text: s.jp, cls: "intro-tr-badge-jp" },
            ].map(({ code, text, cls }, i) => (
              <motion.div
                key={code}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 + i * 0.2 }}
                className="intro-tr-row"
              >
                <span className={`intro-tr-badge ${cls}`}>{code}</span>
                <p className="intro-tr-text">{text}</p>
              </motion.div>
            ))}
          </div>

          <div className="intro-tr-footer">
            <CheckCircle2 size={12} color="#22c55e" />
            Neural Engine · 4ms latency
          </div>
        </motion.div>
      </AnimatePresence>
    </motion.div>
  );
}

function GlobalSlide() {
  const locs = ["Tokyo · JP", "San Francisco · US", "London · UK"];
  return (
    <motion.div
      key="global"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.7 }}
      className="intro-slide intro-slide-global"
    >
      <motion.div
        animate={{ rotate: [0, 2, 0], scale: [1, 1.03, 1] }}
        transition={{ duration: 18, repeat: Infinity, ease: "linear" }}
        className="intro-globe-bg"
      >
        <Globe2 strokeWidth={0.4} />
      </motion.div>

      <div className="intro-global-content">
        <motion.h2
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          className="intro-global-headline"
        >
          One World.<br />
          <span>One Voice.</span>
        </motion.h2>

        <div className="intro-global-nodes">
          {locs.map((loc, i) => (
            <motion.div
              key={loc}
              initial={{ y: 12, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: 0.4 + i * 0.15 }}
              className="intro-node"
            >
              <span className="intro-node-dot" />
              <span className="intro-node-label">{loc}</span>
              <span className="intro-node-status">Connected · 2ms</span>
            </motion.div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}

function IntroShowcase() {
  const [slideIdx, setSlideIdx] = useState(0);

  useEffect(() => {
    const id = setInterval(
      () => setSlideIdx((i) => (i + 1) % SLIDES.length),
      SLIDE_DURATION,
    );
    return () => clearInterval(id);
  }, []);

  const slide = SLIDES[slideIdx];

  return (
    <div className="intro-showcase">
      <AnimatePresence mode="wait">
        {slide === "chaos" && <ChaosSlide />}
        {slide === "clarity" && <ClaritySlide />}
        {slide === "translation" && <TranslationSlide />}
        {slide === "global" && <GlobalSlide />}
      </AnimatePresence>

      {/* Dot indicators */}
      <div className="intro-dots">
        {SLIDES.map((_, i) => (
          <button
            key={i}
            type="button"
            className={`intro-dot${i === slideIdx ? " intro-dot-active" : ""}`}
            onClick={() => setSlideIdx(i)}
            aria-label={`Slide ${i + 1}`}
          />
        ))}
      </div>
    </div>
  );
}

// ─── Action panel ─────────────────────────────────────────────────────────────

export function HomePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [roomInput, setRoomInput] = useState("");
  const [langA, setLangA] = useState<MeetingLanguage | "">("");
  const [langB, setLangB] = useState<MeetingLanguage | "">("");
  const [brseCreateMode, setBrseCreateMode] = useState<BrseCreateMode>(
    () => loadCreateBrseModePreference(),
  );
  const [creating, setCreating] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [joinError, setJoinError] = useState<string | null>(null);
  const landingNotice = getLandingNotice(location.state);

  useEffect(() => {
    saveCreateBrseModePreference(brseCreateMode);
  }, [brseCreateMode]);

  function handleLangAChange(lang: MeetingLanguage | "") {
    setLangA(lang);
    setCreateError(null);
    setValidationError(lang && lang === langB ? "Choose two different languages." : null);
  }

  function handleLangBChange(lang: MeetingLanguage | "") {
    setLangB(lang);
    setCreateError(null);
    setValidationError(lang && lang === langA ? "Choose two different languages." : null);
  }

  async function handleCreateRoom() {
    if (!langA || !langB) { setValidationError("Please select both languages."); return; }
    if (langA === langB) { setValidationError("Choose two different languages."); return; }
    if (!isMeetingLanguage(langA) || !isMeetingLanguage(langB)) {
      setValidationError("Invalid language selection."); return;
    }

    setCreating(true);
    setCreateError(null);
    setValidationError(null);

    try {
      const res = await api.createRoom({
        meeting_languages: [langA, langB],
        ...buildCreateBrsePayload(brseCreateMode),
      });
      navigate(`/rooms/${res.room.room_id}`);
    } catch (err) {
      setCreateError(
        err instanceof ApiError ? mapCreateRoomError(err) : "Could not create room.",
      );
    } finally {
      setCreating(false);
    }
  }

  function handleJoin() {
    const roomId = extractRoomId(roomInput);
    if (!roomId) { setJoinError("Enter a valid room ID or link."); return; }
    setJoinError(null);
    navigate(`/rooms/${roomId}`);
  }

  const langOptions: Array<CustomSelectOption<MeetingLanguage | "">> = [
    { value: "", label: "Select language" },
    ...SUPPORTED_MEETING_LANGUAGES.map((l) => ({ value: l, label: getLanguageLabel(l) })),
  ];

  const canCreate = !!langA && !!langB && langA !== langB;
  const selectedBrseOption =
    BRSE_CREATE_MODE_OPTIONS.find((option) => option.value === brseCreateMode) ??
    BRSE_CREATE_MODE_OPTIONS[0];

  return (
    <main className="hp-root">
      {/* Showcase fills entire background */}
      <IntroShowcase />

      {/* Gradient fade from transparent → dark, covering right half */}
      <div className="hp-fade" aria-hidden="true" />

      {/* Nav — absolute top */}
      <nav className="hp-nav">
        <div className="hp-nav-brand">
          <span className="hp-nav-logo">MQ</span>
          <span className="hp-nav-name">MeetQ</span>
        </div>
        <Link to="/test" className="hp-nav-link">Mic test</Link>
      </nav>

      {/* Right panel — floating overlay */}
      <div className="hp-panel">
        {landingNotice && (
          <div className="hp-notice" role="status">{landingNotice}</div>
        )}

        {/* Create card */}
        <section className="hp-card hp-card-create">
          <div className="hp-card-header">
            <div>
              <p className="hp-card-label">New room</p>
              <h2 className="hp-card-title">Create room</h2>
            </div>
            <div className="hp-card-meta">
              <span>60 min</span>
              <span>{selectedBrseOption.label}</span>
            </div>
          </div>

          <div className="hp-lang-row">
            <div className="hp-lang-slot">
              <label className="hp-lang-label">Language A</label>
              <CustomSelect
                value={langA}
                options={langOptions}
                onChange={handleLangAChange}
                placeholder="Choose language"
                ariaLabel="Language A"
              />
            </div>
            <div className="hp-lang-divider" aria-hidden="true">↔</div>
            <div className="hp-lang-slot">
              <label className="hp-lang-label">Language B</label>
              <CustomSelect
                value={langB}
                options={langOptions}
                onChange={handleLangBChange}
                placeholder="Choose language"
                ariaLabel="Language B"
              />
            </div>
          </div>

          <div className="hp-brse-mode" role="group" aria-label="BRSE output mode">
            {BRSE_CREATE_MODE_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={[
                  "hp-brse-mode-option",
                  option.value === brseCreateMode ? "is-active" : "",
                ].filter(Boolean).join(" ")}
                aria-pressed={option.value === brseCreateMode}
                onClick={() => setBrseCreateMode(option.value)}
              >
                <strong>{option.label}</strong>
                <span>{option.detail}</span>
              </button>
            ))}
          </div>

          {(validationError ?? createError) && (
            <p className="hp-error" role="alert">{validationError ?? createError}</p>
          )}

          <button
            className="hp-btn-primary"
            type="button"
            onClick={() => { void handleCreateRoom(); }}
            disabled={creating || !canCreate}
          >
            {creating ? "Creating…" : "Create Room"}
          </button>
        </section>

        {/* Join row */}
        <section className="hp-card hp-card-join">
          <p className="hp-card-label">Already have a room?</p>
          <div className="hp-join-row">
            <input
              className="hp-join-input"
              value={roomInput}
              onChange={(e) => { setRoomInput(e.target.value); setJoinError(null); }}
              onKeyDown={(e) => { if (e.key === "Enter") handleJoin(); }}
              placeholder="rm_… or room link"
              aria-label="Room ID or link"
            />
            <button className="hp-btn-secondary" type="button" onClick={handleJoin}>
              Open
            </button>
          </div>
          {joinError && <p className="hp-error" role="alert">{joinError}</p>}
        </section>

        <ul className="hp-pills" aria-label="Room defaults">
          <li>60-min rooms</li>
          <li>{selectedBrseOption.detail}</li>
          <li>No account</li>
        </ul>

        <footer className="hp-footer">
          <a className="hp-footer-icon" href="mailto:johnnynguyen882@gmail.com" aria-label="Email" title="Email">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3 6.75A1.75 1.75 0 0 1 4.75 5h14.5A1.75 1.75 0 0 1 21 6.75v10.5A1.75 1.75 0 0 1 19.25 19H4.75A1.75 1.75 0 0 1 3 17.25V6.75Zm2.09-.25 6.5 4.94a.75.75 0 0 0 .91 0l6.5-4.94H5.09Zm14.41 1.88-6.1 4.64a2.25 2.25 0 0 1-2.8 0L4.5 8.38v8.87c0 .14.11.25.25.25h14.5a.25.25 0 0 0 .25-.25V8.38Z" />
            </svg>
          </a>
          <a className="hp-footer-icon" href="https://www.linkedin.com/in/huy8bit/" target="_blank" rel="noopener noreferrer" aria-label="LinkedIn" title="LinkedIn">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6.84 8.2a1.56 1.56 0 1 1 0-3.12 1.56 1.56 0 0 1 0 3.12ZM5.5 9.5h2.68V19H5.5V9.5Zm4.22 0h2.57v1.3h.04c.36-.67 1.24-1.37 2.55-1.37 2.73 0 3.23 1.79 3.23 4.12V19h-2.68v-4.88c0-1.17-.02-2.67-1.63-2.67-1.63 0-1.88 1.27-1.88 2.58V19H9.72V9.5Z" />
            </svg>
          </a>
        </footer>
      </div>
    </main>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getLandingNotice(state: unknown): string | null {
  if (!state || typeof state !== "object") return null;
  const notice = (state as { notice?: unknown }).notice;
  return typeof notice === "string" ? notice : null;
}

function loadCreateBrseModePreference(): BrseCreateMode {
  if (typeof window === "undefined") {
    return "voice_text";
  }

  try {
    const stored = window.localStorage.getItem(CREATE_BRSE_MODE_STORAGE_KEY);
    return isBrseCreateMode(stored) ? stored : "voice_text";
  } catch {
    return "voice_text";
  }
}

function saveCreateBrseModePreference(mode: BrseCreateMode): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(CREATE_BRSE_MODE_STORAGE_KEY, mode);
  } catch {
    // Preference storage is optional.
  }
}

function isBrseCreateMode(value: unknown): value is BrseCreateMode {
  return value === "voice_text" || value === "text_only" || value === "off";
}

function mapCreateRoomError(error: ApiError): string {
  if (error.code === "invalid_meeting_languages") {
    if (error.details?.expected === 2) return "Choose exactly two meeting languages.";
    if (error.details?.unique) return "Choose two different languages.";
    const unsupported = error.details?.unsupported;
    if (Array.isArray(unsupported)) {
      const labels = unsupported
        .filter((l): l is string => typeof l === "string")
        .map((l) => (isMeetingLanguage(l) ? getLanguageLabel(l) : l));
      return labels.length > 0 ? `Unsupported language: ${labels.join(", ")}.` : "Invalid language selection.";
    }
    return "Invalid meeting languages.";
  }
  return error.message;
}

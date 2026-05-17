import { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "motion/react";
import { Zap, Mic2, CheckCircle2, Globe2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useAmbientFloat, useRevealMotion } from "../lib/motion";
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
import { MotionButton } from "../components/MotionButton";

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

// Wave bar heights — staggered for natural audio feel
const WAVE_HEIGHTS = [0.3, 0.7, 1.0, 0.5, 0.8, 0.4, 0.9, 0.6, 0.35, 0.75];
const SPEAKER_WAVE_CENTER_Y = 180;
const SPEAKER_WAVE_MAX_HEIGHT = 42;

function HomeRelayVisual() {
  return (
    <div className="home-relay-visual hrv-root" aria-hidden="true">
      {/* ── Header strip ──────────────────────────────────────────────── */}
      <div className="hrv-header">
        <span className="hrv-live-pill">
          <span className="hrv-live-dot" />
          Live interpretation
        </span>
        <span className="hrv-latency-pill">42 ms relay</span>
      </div>

      {/* ── Pure-SVG diagram — no DOM node positioning ────────────────── */}
      {/*
          ViewBox: 800 × 340
          Layout columns (x):
            VI node:   x=20..170   centre-x=95
            Core:      x=310..490  centre-x=400
            EN node:   x=620..770  centre-x=695  y=60..175
            JA node:   x=620..770  centre-x=695  y=190..305
          Paths connect node edges to core edges.
      */}
      <svg
        className="hrv-diagram"
        viewBox="0 0 800 340"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          {/* Teal flowing gradient (left-to-right) */}
          <linearGradient id="g-in" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#2dd4bf" stopOpacity="0" />
            <stop offset="45%"  stopColor="#2dd4bf" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#2dd4bf" stopOpacity="0" />
          </linearGradient>
          {/* Cyan flowing gradient (left-to-right) */}
          <linearGradient id="g-out" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#22d3ee" stopOpacity="0" />
            <stop offset="45%"  stopColor="#22d3ee" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
          </linearGradient>
          {/* Purple gradient for JA */}
          <linearGradient id="g-ja" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#a78bfa" stopOpacity="0" />
            <stop offset="45%"  stopColor="#a78bfa" stopOpacity="0.80" />
            <stop offset="100%" stopColor="#a78bfa" stopOpacity="0" />
          </linearGradient>
          {/* Radial glow for core */}
          <radialGradient id="g-core-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="#2dd4bf" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#2dd4bf" stopOpacity="0" />
          </radialGradient>
          {/* Node background */}
          <linearGradient id="g-node" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%"   stopColor="#ffffff" stopOpacity="0.88" />
            <stop offset="100%" stopColor="#f0fdf9" stopOpacity="0.72" />
          </linearGradient>
          <linearGradient id="g-node-dark" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%"   stopColor="#162333" stopOpacity="0.90" />
            <stop offset="100%" stopColor="#0d1a28" stopOpacity="0.80" />
          </linearGradient>
          {/* Core gradient */}
          <linearGradient id="g-core-bg" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%"   stopColor="#ffffff" stopOpacity="0.95" />
            <stop offset="100%" stopColor="#f0fdf9" stopOpacity="0.85" />
          </linearGradient>
          {/* Glow blur filter */}
          <filter id="f-glow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="3.5" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="f-glow-soft" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="8" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          {/* Drop shadow for nodes */}
          <filter id="f-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="6" stdDeviation="8" floodColor="#0d1a28" floodOpacity="0.14" />
          </filter>
          <clipPath id="speaker-wave-clip">
            <rect x="44" y="148" width="102" height="64" rx="5" />
          </clipPath>
        </defs>

        {/* ── Background: ambient core glow ─────────────────────────── */}
        <ellipse cx="400" cy="170" rx="130" ry="110"
          fill="url(#g-core-glow)" className="hrv-aura hrv-aura-1" />
        <ellipse cx="400" cy="170" rx="80" ry="68"
          fill="url(#g-core-glow)" className="hrv-aura hrv-aura-2" />

        {/* ═══════════════════════════════════════════════════════════
            TRACK LINES — dim base rails
        ════════════════════════════════════════════════════════════ */}
        {/* VI → Core */}
        <path d="M 170 170 C 240 170, 280 170, 310 170"
          stroke="#2dd4bf" strokeWidth="1.5" fill="none" strokeOpacity="0.18" />
        {/* Core → EN */}
        <path d="M 490 170 C 532 162, 560 104, 620 104"
          stroke="#22d3ee" strokeWidth="1.5" fill="none" strokeOpacity="0.18" />
        {/* Core → JA */}
        <path d="M 490 170 C 532 178, 560 254, 620 254"
          stroke="#a78bfa" strokeWidth="1.5" fill="none" strokeOpacity="0.18" />

        {/* ═══════════════════════════════════════════════════════════
            ANIMATED FLOWING PATHS
        ════════════════════════════════════════════════════════════ */}
        <path className="hrv-flow hrv-flow-in"
          d="M 170 170 C 240 170, 280 170, 310 170"
          stroke="url(#g-in)" strokeWidth="3" fill="none"
          filter="url(#f-glow)" />
        <path className="hrv-flow hrv-flow-en"
          d="M 490 170 C 532 162, 560 104, 620 104"
          stroke="url(#g-out)" strokeWidth="2.5" fill="none"
          filter="url(#f-glow)" />
        <path className="hrv-flow hrv-flow-ja"
          d="M 490 170 C 532 178, 560 254, 620 254"
          stroke="url(#g-ja)" strokeWidth="2.5" fill="none"
          filter="url(#f-glow)" />

        {/* ═══════════════════════════════════════════════════════════
            TRAVELING PARTICLES (animateMotion on hidden paths)
        ════════════════════════════════════════════════════════════ */}
        <path id="p-in" d="M 170 170 C 240 170, 280 170, 310 170" fill="none" stroke="none" />
        <path id="p-en" d="M 490 170 C 532 162, 560 104, 620 104" fill="none" stroke="none" />
        <path id="p-ja" d="M 490 170 C 532 178, 560 254, 620 254" fill="none" stroke="none" />

        <circle r="4" fill="#2dd4bf" filter="url(#f-glow)">
          <animateMotion dur="1.7s" repeatCount="indefinite" begin="0s">
            <mpath xlinkHref="#p-in" />
          </animateMotion>
        </circle>
        <circle r="3.5" fill="#22d3ee" filter="url(#f-glow)">
          <animateMotion dur="1.5s" repeatCount="indefinite" begin="0.5s">
            <mpath xlinkHref="#p-en" />
          </animateMotion>
        </circle>
        <circle r="3.5" fill="#a78bfa" filter="url(#f-glow)">
          <animateMotion dur="1.5s" repeatCount="indefinite" begin="1.1s">
            <mpath xlinkHref="#p-ja" />
          </animateMotion>
        </circle>

        {/* ═══════════════════════════════════════════════════════════
            VI SPEAKER NODE  (x:20–170, y:60–280, centre: 95,170)
        ════════════════════════════════════════════════════════════ */}
        <g className="hrv-node-group" filter="url(#f-shadow)">
          {/* Node card */}
          <rect x="20" y="72" width="150" height="196" rx="20"
            fill="url(#g-node)" stroke="#2dd4bf" strokeOpacity="0.28" strokeWidth="1.5" className="hrv-node-rect" />
          {/* Lang badge */}
          <rect x="36" y="90" width="40" height="26" rx="8"
            fill="#2dd4bf" fillOpacity="0.18" />
          <text x="56" y="107" textAnchor="middle" fontSize="11" fontWeight="800"
            fill="#0d9488" letterSpacing="0.04em">VI</text>
          {/* Label */}
          <text x="95" y="136" textAnchor="middle" fontSize="13" fontWeight="760"
            fill="#0f172a" className="hrv-node-label">Speaker</text>
          {/* Waveform bars — 10 bars centred in node */}
          <g className="hrv-waveform-svg" clipPath="url(#speaker-wave-clip)">
            {WAVE_HEIGHTS.map((h, i) => {
              const barW = 7;
              const gap  = 3;
              const totalW = WAVE_HEIGHTS.length * barW + (WAVE_HEIGHTS.length - 1) * gap;
              const startX = 95 - totalW / 2;
              const barH   = SPEAKER_WAVE_MAX_HEIGHT * h;
              const y      = SPEAKER_WAVE_CENTER_Y - barH / 2;
              return (
                <rect
                  key={i}
                  x={startX + i * (barW + gap)}
                  y={y}
                  width={barW}
                  height={barH}
                  rx="3"
                  fill="#0d9488"
                  className={`hrv-bar-svg hrv-bar-${i % 5}`}
                />
              );
            })}
          </g>
          {/* Sub-label */}
          <text x="95" y="246" textAnchor="middle" fontSize="10" fontWeight="600"
            fill="#64748b">Input</text>
        </g>

        {/* ═══════════════════════════════════════════════════════════
            AI RELAY CORE (x:310–490, y:70–270, centre: 400,170)
        ════════════════════════════════════════════════════════════ */}
        {/* Pulse rings */}
        <rect x="285" y="45" width="230" height="250" rx="50"
          fill="none" stroke="#2dd4bf" strokeOpacity="0.55" strokeWidth="1.5"
          className="hrv-ring-svg hrv-ring-svg-1" />
        <rect x="270" y="30" width="260" height="280" rx="60"
          fill="none" stroke="#2dd4bf" strokeOpacity="0.30" strokeWidth="1"
          className="hrv-ring-svg hrv-ring-svg-2" />
        <rect x="255" y="16" width="290" height="308" rx="70"
          fill="none" stroke="#2dd4bf" strokeOpacity="0.14" strokeWidth="1"
          className="hrv-ring-svg hrv-ring-svg-3" />
        {/* Core card */}
        <g filter="url(#f-shadow)">
          <rect x="310" y="70" width="180" height="200" rx="28"
            fill="url(#g-core-bg)" stroke="#2dd4bf" strokeOpacity="0.40" strokeWidth="2"
            className="hrv-core-rect" />
          {/* AI icon square */}
          <rect x="370" y="96" width="60" height="60" rx="16"
            fill="#0d9488" className="hrv-core-icon-bg" />
          <text x="400" y="130" textAnchor="middle" fontSize="20" fontWeight="840"
            fill="#ffffff">AI</text>
          {/* Relay label */}
          <text x="400" y="186" textAnchor="middle" fontSize="14" fontWeight="820"
            fill="#0f172a" className="hrv-core-label">Relay</text>
          {/* Sub */}
          <text x="400" y="206" textAnchor="middle" fontSize="10" fontWeight="650"
            fill="#64748b">speech · caption</text>
          {/* Processing dots */}
          <circle cx="376" cy="238" r="4" fill="#2dd4bf" className="hrv-proc-dot hrv-proc-1" />
          <circle cx="400" cy="238" r="4" fill="#2dd4bf" className="hrv-proc-dot hrv-proc-2" />
          <circle cx="424" cy="238" r="4" fill="#2dd4bf" className="hrv-proc-dot hrv-proc-3" />
        </g>

        {/* ═══════════════════════════════════════════════════════════
            EN VOICE NODE  (x:620–780, y:44–168, centre: 700,106)
        ════════════════════════════════════════════════════════════ */}
        <g className="hrv-node-group hrv-node-out-en" filter="url(#f-shadow)">
          <rect x="620" y="44" width="160" height="124" rx="18"
            fill="url(#g-node)" stroke="#22d3ee" strokeOpacity="0.32" strokeWidth="1.5" className="hrv-node-rect" />
          {/* Live dot */}
          <circle cx="762" cy="63" r="5" fill="#22d3ee" className="hrv-live-dot-svg hrv-dot-en" />
          {/* Lang badge */}
          <rect x="636" y="62" width="40" height="24" rx="7" fill="#22d3ee" fillOpacity="0.18" />
          <text x="656" y="78" textAnchor="middle" fontSize="10" fontWeight="800"
            fill="#0369a1" letterSpacing="0.04em">EN</text>
          {/* Label */}
          <text x="700" y="106" textAnchor="middle" fontSize="13" fontWeight="760"
            fill="#0f172a" className="hrv-node-label">Voice</text>
          {/* Sample text */}
          <text x="700" y="124" textAnchor="middle" fontSize="10" fontWeight="500"
            fill="#475569">Hello team</text>
          {/* Audio bar mini */}
          {[0.6, 1.0, 0.4, 0.8, 0.5].map((h, i) => (
            <rect key={i}
              x={666 + i * 12} y={148 - 16 * h} width="8" height={16 * h} rx="2"
              fill="#22d3ee" className={`hrv-bar-svg hrv-bar-sm hrv-bar-${i % 5}`} />
          ))}
        </g>

        {/* ═══════════════════════════════════════════════════════════
            JA CAPTION NODE  (x:620–780, y:202–326, centre: 700,264)
        ════════════════════════════════════════════════════════════ */}
        <g className="hrv-node-group hrv-node-out-ja" filter="url(#f-shadow)">
          <rect x="620" y="202" width="160" height="124" rx="18"
            fill="url(#g-node)" stroke="#a78bfa" strokeOpacity="0.32" strokeWidth="1.5" className="hrv-node-rect" />
          {/* Live dot */}
          <circle cx="762" cy="220" r="5" fill="#a78bfa" className="hrv-live-dot-svg hrv-dot-ja-svg" />
          {/* Lang badge */}
          <rect x="636" y="219" width="40" height="24" rx="7" fill="#a78bfa" fillOpacity="0.18" />
          <text x="656" y="235" textAnchor="middle" fontSize="10" fontWeight="800"
            fill="#7c3aed" letterSpacing="0.04em">JA</text>
          {/* Label */}
          <text x="700" y="268" textAnchor="middle" fontSize="13" fontWeight="760"
            fill="#0f172a" className="hrv-node-label">Caption</text>
          {/* Sample text */}
          <text x="700" y="286" textAnchor="middle" fontSize="10" fontWeight="500"
            fill="#475569">こんにちは</text>
          {/* Caption line rects */}
          <rect x="638" y="304" width="70" height="6" rx="3" fill="#a78bfa" fillOpacity="0.35" />
          <rect x="638" y="316" width="50" height="6" rx="3" fill="#a78bfa" fillOpacity="0.20" />
        </g>

        {/* ═══════════════════════════════════════════════════════════
            STATUS CHIPS — bottom strip inside SVG
        ════════════════════════════════════════════════════════════ */}
        <g className="hrv-chips">
          {/* Listening */}
          <rect x="20" y="300" width="108" height="28" rx="14"
            fill="#2dd4bf" fillOpacity="0.10" stroke="#2dd4bf" strokeOpacity="0.30" strokeWidth="1"
            className="hrv-chip-rect hrv-chip-1" />
          <text x="74" y="318" textAnchor="middle" fontSize="11" fontWeight="700"
            fill="#0d9488" className="hrv-chip-text hrv-chip-1t">Listening</text>

          {/* Transcribing */}
          <rect x="140" y="300" width="124" height="28" rx="14"
            fill="#2dd4bf" fillOpacity="0.10" stroke="#2dd4bf" strokeOpacity="0.30" strokeWidth="1"
            className="hrv-chip-rect hrv-chip-2" />
          <text x="202" y="318" textAnchor="middle" fontSize="11" fontWeight="700"
            fill="#0d9488" className="hrv-chip-text hrv-chip-2t">Transcribing</text>

          {/* Relaying */}
          <rect x="276" y="300" width="96" height="28" rx="14"
            fill="#2dd4bf" fillOpacity="0.10" stroke="#2dd4bf" strokeOpacity="0.30" strokeWidth="1"
            className="hrv-chip-rect hrv-chip-3" />
          <text x="324" y="318" textAnchor="middle" fontSize="11" fontWeight="700"
            fill="#0d9488" className="hrv-chip-text hrv-chip-3t">Relaying</text>
        </g>
      </svg>

      {/* ── Transcript feed ────────────────────────────────────────────── */}
      <div className="hrv-feed-strip">
        <div className="hrv-feed-item hrv-feed-vi-row">
          <span className="hrv-feed-tag hrv-feed-tag-vi">VI</span>
          <span className="hrv-feed-text">Xin chào team, mình bắt đầu nhé.</span>
        </div>
        <div className="hrv-feed-item hrv-feed-ai-row">
          <span className="hrv-feed-tag hrv-feed-tag-ai">AI</span>
          <span className="hrv-feed-text hrv-feed-text-muted">Detecting intent, terms, and timing…</span>
        </div>
        <div className="hrv-feed-item hrv-feed-en-row">
          <span className="hrv-feed-tag hrv-feed-tag-en">EN</span>
          <span className="hrv-feed-text">Hello team, we are ready to start.</span>
        </div>
      </div>
    </div>
  );
}

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
  const showcaseMotionRef = useAmbientFloat<HTMLDivElement>({
    distance: 4,
    rotate: 0.12,
  });

  useEffect(() => {
    const id = setInterval(
      () => setSlideIdx((i) => (i + 1) % SLIDES.length),
      SLIDE_DURATION,
    );
    return () => clearInterval(id);
  }, []);

  const slide = SLIDES[slideIdx];

  return (
    <div className="intro-showcase" ref={showcaseMotionRef}>
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
  const pageMotionRef = useRevealMotion<HTMLElement>({
    selector: "[data-home-motion]",
    distance: 18,
    duration: 560,
    stagger: 72,
    scaleFrom: 0.992,
  });
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
  const createAttentionKey = canCreate
    ? `${langA}-${langB}-${brseCreateMode}`
    : null;

  return (
    <main className="hp-root" ref={pageMotionRef}>
      {/* Nav — absolute top */}
      <nav className="hp-nav" data-home-motion>
        <div className="hp-nav-brand">
          <span className="hp-nav-name">MeetQ</span>
        </div>
        <Link to="/test" className="hp-nav-link">Mic test</Link>
      </nav>

      <div className="hp-hero-shell">
        <section className="hp-showcase-hero" aria-label="MeetQ AI meeting platform" data-home-motion>
          <h1 className="hp-sr-only">MeetQ AI multilingual meetings</h1>
          <HomeRelayVisual />
        </section>

        {/* Gradient fade from transparent → dark, covering right half */}
        <div className="hp-fade" aria-hidden="true" />

        {/* Right panel — room controls */}
        <div className="hp-panel hp-room-panel">
          {landingNotice && (
            <div className="hp-notice" role="status">{landingNotice}</div>
          )}

          {/* Create card */}
          <section className="hp-card hp-card-create hp-room-card" data-home-motion>
            <div className="hp-card-header hp-room-card-header">
              <div>
                <p className="hp-card-label">New room</p>
                <h2 className="hp-card-title">Start an AI-assisted meeting</h2>
                <p className="hp-card-subtitle">
                  Choose the language pair and how MeetQ relays speech, captions, and AI voice.
                </p>
              </div>
            </div>

            <section className="hp-create-section hp-language-section hp-form-section">
              <div className="hp-section-heading">
                <span>Conversation pair</span>
              </div>
              <div className="hp-lang-row">
                <div className="hp-lang-slot">
                  <label className="hp-lang-label">From</label>
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
                  <label className="hp-lang-label">To</label>
                  <CustomSelect
                    value={langB}
                    options={langOptions}
                    onChange={handleLangBChange}
                    placeholder="Choose language"
                    ariaLabel="Language B"
                  />
                </div>
              </div>
            </section>

            <section className="hp-create-section hp-option-section hp-form-section hp-relay-section">
              <div className="hp-section-heading">
                <span>AI relay</span>
              </div>
              <div className="hp-brse-mode" role="group" aria-label="BRSE output mode">
                {BRSE_CREATE_MODE_OPTIONS.map((option) => (
                  <MotionButton
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
                    {option.value === brseCreateMode ? <span>{option.detail}</span> : null}
                  </MotionButton>
                ))}
              </div>
            </section>

            {(validationError ?? createError) && (
              <p className="hp-error" role="alert">{validationError ?? createError}</p>
            )}

            <div className="hp-cta-section">
              <MotionButton
                className="hp-btn-primary"
                type="button"
                onClick={() => { void handleCreateRoom(); }}
                disabled={creating || !canCreate}
                attentionKey={createAttentionKey}
              >
                {creating ? "Creating…" : "Create room"}
              </MotionButton>
              <p>60-minute room. No account required.</p>
            </div>
          </section>

          {/* Join row */}
          <section className="hp-card hp-card-join hp-join-card" data-home-motion>
            <p className="hp-card-label">Join room</p>
            <div className="hp-join-row">
              <input
                className="hp-join-input"
                value={roomInput}
                onChange={(e) => { setRoomInput(e.target.value); setJoinError(null); }}
                onKeyDown={(e) => { if (e.key === "Enter") handleJoin(); }}
                placeholder="rm_… or room link"
                aria-label="Room ID or link"
              />
              <MotionButton className="hp-btn-secondary" type="button" onClick={handleJoin}>
                Open
              </MotionButton>
            </div>
            {joinError && <p className="hp-error" role="alert">{joinError}</p>}
          </section>

          <footer className="hp-footer" data-home-motion>
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

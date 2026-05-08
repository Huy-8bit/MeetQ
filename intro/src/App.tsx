/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { 
  Globe, 
  Mic2, 
  Volume2, 
  CheckCircle2, 
  Zap,
  Globe2,
  Play
} from 'lucide-react';

// --- Types ---
type Scene = 'INTRO_CHAOS' | 'TRANSITION' | 'CLARITY_REVEAL' | 'REALTIME_TRANSLATION' | 'GLOBAL_IMPACT' | 'OUTRO';

export default function App() {
  const [scene, setScene] = useState<Scene>('INTRO_CHAOS');
  const [isPlaying, setIsPlaying] = useState(false);

  // Storyboard Timing
  useEffect(() => {
    if (!isPlaying) return;

    const sequence = [
      { scene: 'INTRO_CHAOS' as Scene, duration: 6000 },
      { scene: 'TRANSITION' as Scene, duration: 1000 },
      { scene: 'CLARITY_REVEAL' as Scene, duration: 4000 },
      { scene: 'REALTIME_TRANSLATION' as Scene, duration: 8000 },
      { scene: 'GLOBAL_IMPACT' as Scene, duration: 6000 },
      { scene: 'OUTRO' as Scene, duration: 5000 },
    ];

    let timer = 0;
    const timeouts: NodeJS.Timeout[] = [];

    sequence.forEach((item, index) => {
      const timeout = setTimeout(() => {
        setScene(item.scene);
      }, timer);
      timeouts.push(timeout);
      timer += item.duration;
    });

    return () => timeouts.forEach(t => clearTimeout(t));
  }, [isPlaying]);

  return (
    <div className="relative w-full h-screen bg-black overflow-hidden font-sans">
      {!isPlaying && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-black/80 backdrop-blur-md">
          <motion.div 
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="text-center"
          >
            <h1 className="text-6xl font-display font-bold tracking-tighter mb-4 text-white">meetQ</h1>
            <p className="text-gray-400 mb-8 max-w-sm">Experience the 30-second premiere of communication's future.</p>
            <button 
              onClick={() => setIsPlaying(true)}
              className="group relative flex items-center gap-3 px-8 py-4 bg-white text-black font-bold rounded-full hover:bg-brand-blue hover:text-white transition-all duration-500 overflow-hidden"
            >
              <Play className="w-5 h-5 fill-current" />
              <span>WATCH PREMIERE</span>
              <div className="absolute inset-0 bg-gradient-to-r from-brand-blue to-brand-purple opacity-0 group-hover:opacity-100 -z-10 transition-opacity" />
            </button>
          </motion.div>
        </div>
      )}

      <AnimatePresence mode="wait">
        {scene === 'INTRO_CHAOS' && <ChaosScene key="chaos" />}
        {scene === 'TRANSITION' && <TransitionScene key="transition" />}
        {scene === 'CLARITY_REVEAL' && <ClarityReveal key="clarity" />}
        {scene === 'REALTIME_TRANSLATION' && <TranslationScene key="translation" />}
        {scene === 'GLOBAL_IMPACT' && <GlobalImpact key="global" />}
        {scene === 'OUTRO' && <OutroScene key="outro" reset={() => { setIsPlaying(false); setScene('INTRO_CHAOS'); }} />}
      </AnimatePresence>
    </div>
  );
}

// --- Scene Components ---

function ChaosScene() {
  const [glitchText, setGlitchText] = useState("Can everyone hear me?");
  
  useEffect(() => {
    const texts = ["Xin chào?", "Tôi không nghe thấy gì...", "Wait, the screen is frozen", "Est-ce que ça marche?", "Moshi moshi?"];
    let i = 0;
    const interval = setInterval(() => {
      setGlitchText(texts[i % texts.length]);
      i++;
    }, 800);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="absolute inset-0 flex items-center justify-center bg-zinc-900"
    >
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 p-4 w-full h-full max-w-5xl mx-auto shaky">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="relative bg-zinc-800 rounded-lg overflow-hidden border border-zinc-700">
            <img 
              src={`https://picsum.photos/seed/${i + 10}/400/300?grayscale&blur=2`}
              className="w-full h-full object-cover opacity-60 grayscale"
              alt="Participant"
              referrerPolicy="no-referrer"
            />
            <div className="absolute inset-0 bg-black/20" />
            <div className="absolute top-2 left-2 px-2 py-0.5 rounded bg-black/60 text-[10px] font-mono">
              USER_{i} | CONNECTION LAGGING
            </div>
            {i === 2 && (
              <div className="absolute bottom-4 left-0 right-0 px-4 text-center">
                <span className="bg-red-500/80 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-white">Distorted Audio</span>
              </div>
            )}
          </div>
        ))}
      </div>
      
      <div className="absolute inset-x-0 bottom-20 px-8 pointer-events-none">
        <motion.div 
          key={glitchText}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-3xl md:text-5xl font-display font-medium text-center glitch"
          data-text={glitchText}
        >
          {glitchText}
        </motion.div>
      </div>

      {/* Overlay Noise */}
      <div className="absolute inset-0 pointer-events-none bg-[url('https://transparenttextures.com/patterns/carbon-fibre.png')] opacity-10 mix-blend-overlay" />
    </motion.div>
  );
}

function TransitionScene() {
  return (
    <motion.div 
      initial={{ opacity: 0, scale: 1.5 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0 }}
      className="absolute inset-0 bg-white z-[100] flex items-center justify-center"
    >
      <div className="text-black font-display text-4xl tracking-[1em] opacity-20">SILENCE</div>
    </motion.div>
  );
}

function ClarityReveal() {
  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="absolute inset-0 bg-black flex flex-col items-center justify-center"
    >
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 1.5, ease: "easeOut" }}
        className="w-full h-full p-8"
      >
        <div className="relative w-full h-full bg-zinc-900 rounded-[2rem] border border-white/10 overflow-hidden shadow-2xl flex items-center justify-center">
          <img 
            src="https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?auto=format&fit=crop&q=80&w=1200"
            className="absolute inset-0 w-full h-full object-cover opacity-80"
            alt="Futuristic UI background"
            referrerPolicy="no-referrer"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black via-transparent to-black/40" />
          
          <div className="relative text-center z-10 px-8">
            <motion.div
              initial={{ y: 20, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: 1 }}
              className="inline-flex items-center gap-2 mb-6 px-4 py-1.5 rounded-full bg-brand-blue/20 border border-brand-blue/30 text-brand-blue text-sm font-medium tracking-wide"
            >
              <Zap className="w-4 h-4 fill-current" />
              <span>AI RECONSTRUCTION ACTIVE</span>
            </motion.div>
            <h2 className="text-5xl md:text-7xl font-display font-medium tracking-tight leading-none mb-4">
              Purity in <span className="text-brand-blue">every word.</span>
            </h2>
            <p className="text-zinc-400 text-lg md:text-xl max-w-xl mx-auto font-light">Zero noise. Zero delay. Absolute understanding.</p>
          </div>

          <div className="absolute bottom-12 inset-x-0 px-12 flex justify-between items-end">
             <div className="flex gap-4">
               {[1, 2, 3].map(i => (
                 <div key={i} className="w-1.5 h-12 bg-white/20 rounded-full overflow-hidden">
                   <motion.div 
                    animate={{ height: ['20%', '90%', '40%', '70%'] }}
                    transition={{ duration: 1.5, repeat: Infinity, delay: i * 0.2 }}
                    className="w-full bg-brand-blue shadow-[0_0_15px_rgba(0,210,255,0.6)]"
                   />
                 </div>
               ))}
             </div>
             <div className="bg-white/5 backdrop-blur-xl border border-white/10 p-4 rounded-2xl flex items-center gap-4">
                <Mic2 className="text-brand-blue w-6 h-6" />
                <div className="text-left">
                  <div className="text-xs uppercase tracking-widest text-zinc-500 font-bold">Input</div>
                  <div className="text-sm font-medium">Vietnamese (Detected)</div>
                </div>
             </div>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

function TranslationScene() {
  const transcriptSteps = [
    { vi: "Xin chào, tôi rất hân hạnh được giới thiệu về meetQ.", en: "Hello, I am honored to introduce meetQ.", jp: "こんにちは、meetQをご紹介できて光栄です。" },
    { vi: "Công nghệ này sẽ thay đổi cách chúng ta giao tiếp.", en: "This technology will change how we communicate.", jp: "この技術は私たちのコミュニケーション方法を変えます。" },
  ];

  const [step, setStep] = useState(0);

  useEffect(() => {
    const timeout = setTimeout(() => setStep(1), 4000);
    return () => clearTimeout(timeout);
  }, []);

  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="absolute inset-0 bg-black p-4 flex flex-col items-center justify-center"
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 w-full max-w-6xl">
        {/* Speaker View */}
        <div className="relative aspect-video bg-zinc-900 rounded-3xl overflow-hidden border border-white/10 group">
          <img 
            src="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&q=80&w=800"
            className="w-full h-full object-cover"
            alt="Speaker"
            referrerPolicy="no-referrer"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent" />
          <div className="absolute bottom-6 left-6 flex items-center gap-3">
             <div className="w-12 h-12 rounded-full border-2 border-brand-blue flex items-center justify-center p-1">
               <div className="w-full h-full bg-brand-blue rounded-full animate-pulse" />
             </div>
             <div>
               <div className="text-xs font-bold text-brand-blue uppercase tracking-tighter">Live Voice Analysis</div>
               <div className="text-lg font-medium">Duy Nguyễn</div>
             </div>
          </div>
        </div>

        {/* Translation UI */}
        <div className="flex flex-col gap-4 justify-center">
          <motion.div 
            key={step}
            initial={{ x: 20, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            className="bg-zinc-900/50 backdrop-blur-xl border border-brand-blue/30 p-8 rounded-[2.5rem] shadow-[0_0_40px_rgba(0,210,255,0.1)]"
          >
            <div className="mb-8">
              <div className="text-[10px] uppercase tracking-[0.3em] text-brand-blue font-bold mb-2">Original</div>
              <p className="text-xl leading-relaxed text-zinc-300 font-light italic">"{transcriptSteps[step].vi}"</p>
            </div>
            
            <div className="space-y-6">
              <div className="flex gap-4 items-start translate-x-4">
                 <div className="w-8 h-8 rounded-full bg-white text-black flex items-center justify-center flex-shrink-0 text-[10px] font-bold">EN</div>
                 <p className="text-xl font-display font-medium leading-relaxed group">
                   {transcriptSteps[step].en}
                   <motion.span 
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{ duration: 1, delay: 0.5 }}
                    className="block h-0.5 bg-brand-blue mt-1 origin-left opacity-30" 
                   />
                 </p>
              </div>
              <div className="flex gap-4 items-start translate-x-8">
                 <div className="w-8 h-8 rounded-full bg-brand-purple text-white flex items-center justify-center flex-shrink-0 text-[10px] font-bold">JP</div>
                 <p className="text-xl font-display font-medium leading-relaxed">
                   {transcriptSteps[step].jp}
                   <motion.span 
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{ duration: 1, delay: 0.8 }}
                    className="block h-0.5 bg-brand-purple mt-1 origin-left opacity-30" 
                   />
                 </p>
              </div>
            </div>
          </motion.div>
          
          <div className="flex gap-2 justify-end px-4">
            <CheckCircle2 className="w-4 h-4 text-green-500" />
            <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">Neural Engine Optimized • 4ms Latency</span>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function GlobalImpact() {
  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="absolute inset-0 bg-black flex flex-col items-center justify-center"
    >
      <div className="relative w-full h-full max-w-7xl mx-auto flex items-center justify-center overflow-hidden">
        <motion.div
           animate={{ 
             scale: [1, 1.05, 1],
             rotate: [0, 1, 0]
           }}
           transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
           className="opacity-30"
        >
          <Globe2 className="w-[80vw] h-[80vw] text-white opacity-5" strokeWidth={0.5} />
        </motion.div>

        {/* Global Connection Visualization */}
        <div className="absolute inset-0 flex flex-col items-center justify-center z-10 px-6">
           <motion.div 
            initial={{ y: 30, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            className="text-center"
           >
              <h2 className="text-6xl md:text-8xl font-display font-bold tracking-tighter mb-8 leading-none">
                One World. <br />
                <span className="bg-gradient-to-r from-brand-blue to-brand-purple bg-clip-text text-transparent">One Voice.</span>
              </h2>
           </motion.div>

           <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mt-12 w-full max-w-4xl">
              {[
                { label: "Tokyo", country: "Japan", time: "Present" },
                { label: "San Francisco", country: "USA", time: "Present" },
                { label: "London", country: "UK", time: "Present" }
              ].map((loc, i) => (
                <motion.div
                  key={i}
                  initial={{ y: 20, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  transition={{ delay: i * 0.2 + 1 }}
                  className="bg-white/5 border border-white/10 p-6 rounded-3xl backdrop-blur-md"
                >
                  <div className="flex items-center gap-2 mb-3">
                    <div className="w-2 h-2 rounded-full bg-brand-blue animate-pulse" />
                    <span className="text-[10px] font-bold uppercase tracking-widest text-brand-blue">{loc.label}</span>
                  </div>
                  <div className="text-xl font-display font-medium">Connected</div>
                  <div className="text-sm text-zinc-500 font-light italic">Latency: 2ms via meetQ</div>
                </motion.div>
              ))}
           </div>
        </div>

        {/* Floating Particles/Lines Simulation */}
        {[...Array(8)].map((_, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0 }}
            animate={{ 
              opacity: [0, 1, 0],
              x: [Math.random() * 500 - 250, Math.random() * 500 - 250],
              y: [Math.random() * 500 - 250, Math.random() * 500 - 250]
            }}
            transition={{ duration: 3, repeat: Infinity, delay: i * 0.5 }}
            className="absolute w-[1px] h-[100px] bg-gradient-to-t from-brand-blue to-transparent"
            style={{ 
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              transform: `rotate(${Math.random() * 360}deg)`
            }}
          />
        ))}
      </div>
    </motion.div>
  );
}

function OutroScene({ reset }: { reset: () => void }) {
  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="absolute inset-0 bg-black flex flex-col items-center justify-center p-8"
    >
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 1 }}
        className="text-center"
      >
        <div className="relative mb-12 inline-block">
          <motion.div
            animate={{ scale: [1, 1.1, 1], opacity: [0.3, 0.5, 0.3] }}
            transition={{ duration: 4, repeat: Infinity }}
            className="absolute inset-x-0 -inset-y-4 bg-brand-blue blur-[80px] -z-10"
          />
          <h1 className="text-8xl md:text-9xl font-display font-bold tracking-tighter text-white">meetQ</h1>
        </div>
        
        <div className="space-y-4">
          <p className="text-2xl md:text-3xl font-display font-light text-zinc-400">Human connection, without borders.</p>
          <div className="flex gap-4 justify-center items-center">
            <span className="px-4 py-1 rounded-full border border-zinc-800 text-[10px] font-bold tracking-widest text-zinc-500 uppercase">Available Q3 2026</span>
            <span className="w-1.5 h-1.5 rounded-full bg-zinc-700" />
            <span className="px-4 py-1 rounded-full border border-zinc-800 text-[10px] font-bold tracking-widest text-zinc-500 uppercase">iOS • Android • Web</span>
          </div>
        </div>

        <motion.button
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1 }}
          onClick={reset}
          className="mt-16 text-zinc-600 hover:text-white text-xs uppercase tracking-[0.4em] font-bold transition-colors"
        >
          Watch Again
        </motion.button>
      </motion.div>

      <div className="absolute bottom-8 text-[10px] tracking-[0.2em] text-zinc-700 uppercase font-bold">
        Designed for the Infinite Human Connection
      </div>
    </motion.div>
  );
}

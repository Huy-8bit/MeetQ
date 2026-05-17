import { useLayoutEffect, useRef, type DependencyList, type RefObject } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { usePrefersReducedMotion } from "./motion";

gsap.registerPlugin(ScrollTrigger, SplitText);

type TextAnimationKind = "fade" | "line" | "words" | "cta" | "highlight";

interface TextAnimationOptions {
  selector?: string;
  dependencies?: DependencyList;
  once?: boolean;
}

const DEFAULT_TEXT_SELECTOR = "[data-text-animate]";

export function useTextAnimationRoot<TElement extends HTMLElement>(
  options: TextAnimationOptions = {},
): RefObject<TElement> {
  const ref = useRef<TElement>(null);
  useTextAnimations(ref, options);
  return ref;
}

export function useTextAnimations<TElement extends HTMLElement>(
  rootRef: RefObject<TElement>,
  {
    selector = DEFAULT_TEXT_SELECTOR,
    dependencies = [],
    once = true,
  }: TextAnimationOptions = {},
): void {
  const reducedMotion = usePrefersReducedMotion();

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) {
      return;
    }

    const targets = gsap.utils
      .toArray<HTMLElement>(selector, root)
      .filter((target) => shouldAnimateTextTarget(target));

    if (targets.length === 0) {
      return;
    }

    if (reducedMotion) {
      gsap.set(targets, { autoAlpha: 1, y: 0, x: 0, scale: 1, clearProps: "all" });
      return;
    }

    const ctx = gsap.context(() => {
      targets.forEach((target) => {
        const kind = getTextAnimationKind(target);
        const delay = getNumberDatasetValue(target.dataset.textAnimateDelay, 0);

        if (kind === "line" || kind === "words") {
          const split = SplitText.create(target, {
            type: kind === "line" ? "lines" : "words",
            mask: kind === "line" ? "lines" : "words",
            linesClass: "text-anim-line",
            wordsClass: "text-anim-word",
            aria: "auto",
            reduceWhiteSpace: false,
          });
          const splitTargets = kind === "line" ? split.lines : split.words;

          gsap.from(splitTargets, {
            autoAlpha: 0,
            yPercent: kind === "line" ? 105 : 60,
            duration: kind === "line" ? 0.62 : 0.42,
            delay,
            stagger: kind === "line" ? 0.075 : 0.025,
            ease: "power3.out",
            clearProps: "transform,opacity,visibility",
            scrollTrigger: {
              trigger: target,
              start: "top 88%",
              once,
            },
          });
          return;
        }

        if (kind === "highlight") {
          gsap.fromTo(
            target,
            { backgroundSize: "0% 38%" },
            {
              backgroundSize: "100% 38%",
              duration: 0.56,
              delay,
              ease: "power2.out",
              scrollTrigger: {
                trigger: target,
                start: "top 90%",
                once,
              },
            },
          );
          return;
        }

        gsap.from(target, {
          autoAlpha: 0,
          y: kind === "cta" ? 8 : 14,
          scale: kind === "cta" ? 0.992 : 1,
          duration: kind === "cta" ? 0.38 : 0.48,
          delay,
          ease: "power2.out",
          clearProps: "transform,opacity,visibility",
          scrollTrigger: {
            trigger: target,
            start: "top 90%",
            once,
          },
        });
      });
    }, root);

    return () => {
      ctx.revert();
    };
  }, [rootRef, selector, once, reducedMotion, ...dependencies]);
}

function shouldAnimateTextTarget(target: HTMLElement): boolean {
  if (!target.textContent?.trim()) {
    return false;
  }

  return !target.closest(
    "[data-text-animation-disabled], .custom-select-menu, .audio-sinks",
  );
}

function getTextAnimationKind(target: HTMLElement): TextAnimationKind {
  const value = target.dataset.textAnimate;
  if (
    value === "line"
    || value === "words"
    || value === "cta"
    || value === "highlight"
  ) {
    return value;
  }
  return "fade";
}

function getNumberDatasetValue(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

import {
  useEffect,
  useRef,
  useState,
  type DependencyList,
  type FocusEventHandler,
  type PointerEventHandler,
  type RefObject,
} from "react";
import anime from "animejs";

type AnimeHandle = {
  pause?: () => void;
};

type MotionAxis = "x" | "y" | "none";

interface RevealOptions {
  selector?: string;
  axis?: MotionAxis;
  distance?: number;
  duration?: number;
  delay?: number;
  stagger?: number;
  scaleFrom?: number;
  easing?: string;
}

interface PanelTransitionOptions {
  axis?: MotionAxis;
  distance?: number;
  duration?: number;
  easing?: string;
}

interface PressHandlers<T extends HTMLElement> {
  onPointerDown: PointerEventHandler<T>;
  onPointerUp: PointerEventHandler<T>;
  onPointerCancel: PointerEventHandler<T>;
  onPointerLeave: PointerEventHandler<T>;
  onBlur: FocusEventHandler<T>;
}

export const motionTokens = {
  duration: {
    press: 110,
    micro: 160,
    tab: 210,
    panel: 260,
    reveal: 420,
    page: 520,
    ambient: 6800,
  },
  distance: {
    xs: 4,
    sm: 8,
    md: 14,
    lg: 24,
  },
  stagger: {
    tight: 24,
    normal: 42,
    spacious: 64,
  },
  easing: {
    standard: "easeOutCubic",
    emphasized: "easeOutExpo",
    calm: "easeInOutSine",
  },
} as const;

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }

  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function usePrefersReducedMotion(): boolean {
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }

    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = () => setReducedMotion(media.matches);

    handleChange();
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", handleChange);
      return () => media.removeEventListener("change", handleChange);
    }

    media.addListener(handleChange);
    return () => media.removeListener(handleChange);
  }, []);

  return reducedMotion;
}

export function useRevealMotion<TElement extends HTMLElement>({
  selector = "[data-motion-reveal]",
  axis = "y",
  distance = motionTokens.distance.md,
  duration = motionTokens.duration.reveal,
  delay = 0,
  stagger = motionTokens.stagger.normal,
  scaleFrom = 0.985,
  easing = motionTokens.easing.emphasized,
  dependencies = [],
}: RevealOptions & { dependencies?: DependencyList } = {}): RefObject<TElement> {
  const ref = useRef<TElement>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) {
      return;
    }

    const animation = revealWithin(root, {
      selector,
      axis,
      distance,
      duration,
      delay,
      stagger,
      scaleFrom,
      easing,
    });

    return () => stopAnimation(animation, root, selector);
  }, dependencies);

  return ref;
}

export function useAmbientFloat<TElement extends HTMLElement>({
  distance = 5,
  rotate = 0.18,
  duration = motionTokens.duration.ambient,
}: {
  distance?: number;
  rotate?: number;
  duration?: number;
} = {}): RefObject<TElement> {
  const ref = useRef<TElement>(null);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    const node = ref.current;
    if (!node) {
      return;
    }

    anime.remove(node);
    if (reducedMotion) {
      anime.set(node, { translateY: 0, rotate: 0 });
      return () => anime.remove(node);
    }

    const animation = anime({
      targets: node,
      translateY: [-distance, distance],
      rotate: [-rotate, rotate],
      duration,
      direction: "alternate",
      loop: true,
      easing: motionTokens.easing.calm,
    }) as AnimeHandle;

    return () => stopAnimation(animation, node);
  }, [distance, duration, reducedMotion, rotate]);

  return ref;
}

export function usePanelTransition<TElement extends HTMLElement>(
  open: boolean,
  {
    axis = "x",
    distance = motionTokens.distance.lg,
    duration = motionTokens.duration.panel,
    easing = motionTokens.easing.emphasized,
  }: PanelTransitionOptions = {},
): RefObject<TElement> {
  const ref = useRef<TElement>(null);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    const node = ref.current;
    if (!node) {
      return;
    }

    anime.remove(node);
    const axisProp = getAxisProperty(axis);
    if (reducedMotion) {
      anime.set(node, axisProp ? { opacity: open ? 1 : 0, [axisProp]: 0 } : { opacity: open ? 1 : 0 });
      return () => anime.remove(node);
    }

    const params: Record<string, unknown> = {
      targets: node,
      opacity: open ? [0.55, 1] : [1, 0],
      duration,
      easing,
    };
    if (axisProp) {
      params[axisProp] = open ? [distance, 0] : [0, Math.round(distance / 2)];
    }

    const animation = anime(params) as AnimeHandle;
    return () => stopAnimation(animation, node);
  }, [axis, distance, duration, easing, open, reducedMotion]);

  return ref;
}

export function useContentSwitchMotion<TElement extends HTMLElement>(
  switchKey: unknown,
  {
    selector = "[data-motion-panel-item]",
    axis = "y",
    distance = motionTokens.distance.sm,
    duration = motionTokens.duration.tab,
    stagger = motionTokens.stagger.tight,
    easing = motionTokens.easing.standard,
  }: RevealOptions = {},
): RefObject<TElement> {
  const ref = useRef<TElement>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) {
      return;
    }

    const animation = revealWithin(root, {
      selector,
      axis,
      distance,
      duration,
      stagger,
      easing,
      scaleFrom: 0.995,
    });

    return () => stopAnimation(animation, root, selector);
  }, [axis, distance, duration, easing, selector, stagger, switchKey]);

  return ref;
}

export function useDropdownMotion<TElement extends HTMLElement>(
  open: boolean,
): RefObject<TElement> {
  const ref = useRef<TElement>(null);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    const menu = ref.current;
    if (!open || !menu) {
      return;
    }

    anime.remove(menu);
    const options = Array.from(menu.querySelectorAll(".custom-select-option"));
    anime.remove(options);

    if (reducedMotion) {
      anime.set([menu, ...options], { opacity: 1, translateY: 0, scale: 1 });
      return () => {
        anime.remove(menu);
        anime.remove(options);
      };
    }

    const menuAnimation = anime({
      targets: menu,
      opacity: [0, 1],
      translateY: [-4, 0],
      scale: [0.985, 1],
      duration: motionTokens.duration.micro,
      easing: motionTokens.easing.standard,
    }) as AnimeHandle;

    const optionAnimation = anime({
      targets: options,
      opacity: [0, 1],
      translateY: [4, 0],
      duration: motionTokens.duration.tab,
      delay: anime.stagger(18, { start: 35 }),
      easing: motionTokens.easing.standard,
    }) as AnimeHandle;

    return () => {
      stopAnimation(menuAnimation, menu);
      stopAnimation(optionAnimation, options);
    };
  }, [open, reducedMotion]);

  return ref;
}

export function useDrawerRevealMotion<TElement extends HTMLElement>(
  motionKey?: unknown,
): RefObject<TElement> {
  const ref = useRef<TElement>(null);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    const root = ref.current;
    if (!root) {
      return;
    }

    const backdrop = root.querySelector(".settings-drawer-backdrop");
    const drawer = root.querySelector(".settings-drawer");
    const contentItems = Array.from(root.querySelectorAll(".settings-drawer-content > *"));

    anime.remove([backdrop, drawer, ...contentItems].filter(Boolean));

    if (reducedMotion) {
      anime.set([backdrop, drawer, ...contentItems].filter(Boolean), {
        opacity: 1,
        translateX: 0,
        translateY: 0,
      });
      return () => anime.remove([backdrop, drawer, ...contentItems].filter(Boolean));
    }

    const timeline = anime.timeline({
      easing: motionTokens.easing.emphasized,
      duration: motionTokens.duration.panel,
    });

    if (backdrop) {
      timeline.add({
        targets: backdrop,
        opacity: [0, 1],
        duration: motionTokens.duration.panel,
      }, 0);
    }

    if (drawer) {
      timeline.add({
        targets: drawer,
        opacity: [0.7, 1],
        translateX: [28, 0],
        duration: motionTokens.duration.panel + 80,
      }, 0);
    }

    if (contentItems.length > 0) {
      timeline.add({
        targets: contentItems,
        opacity: [0, 1],
        translateY: [8, 0],
        duration: motionTokens.duration.tab,
        delay: anime.stagger(28),
      }, 90);
    }

    return () => {
      timeline.pause?.();
      anime.remove([backdrop, drawer, ...contentItems].filter(Boolean));
    };
  }, [motionKey, reducedMotion]);

  return ref;
}

export function useAnimePress<TElement extends HTMLElement>(
  disabled = false,
): { ref: RefObject<TElement>; motionPressHandlers: PressHandlers<TElement> } {
  const ref = useRef<TElement>(null);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    const node = ref.current;
    return () => {
      if (node) {
        anime.remove(node);
      }
    };
  }, []);

  const animateTo = (scale: number, translateY: number) => {
    const node = ref.current;
    if (!node || disabled || reducedMotion) {
      return;
    }

    anime.remove(node);
    anime({
      targets: node,
      scale,
      translateY,
      duration: motionTokens.duration.press,
      easing: motionTokens.easing.standard,
      complete: () => {
        if (scale === 1 && translateY === 0) {
          node.style.transform = "";
        }
      },
    });
  };

  const release = () => animateTo(1, 0);

  return {
    ref,
    motionPressHandlers: {
      onPointerDown: (event) => {
        if (event.button !== 0) {
          return;
        }
        animateTo(0.982, 1);
      },
      onPointerUp: release,
      onPointerCancel: release,
      onPointerLeave: release,
      onBlur: release,
    },
  };
}

export function useAttentionPulse<TElement extends HTMLElement>(
  trigger: unknown,
  enabled = true,
): RefObject<TElement> {
  const ref = useRef<TElement>(null);

  useEffect(() => {
    if (!trigger) {
      return;
    }

    const animation = animateAttentionPulse(ref.current, enabled);
    return () => stopAnimation(animation, ref.current ?? undefined);
  }, [enabled, trigger]);

  return ref;
}

export function animateAttentionPulse(
  node: HTMLElement | null,
  enabled = true,
): AnimeHandle | null {
  if (!node || !enabled || prefersReducedMotion()) {
    return null;
  }

  anime.remove(node);
  return anime({
    targets: node,
    scale: [1, 1.012, 1],
    duration: 380,
    easing: motionTokens.easing.standard,
    complete: () => {
      node.style.transform = "";
    },
  }) as AnimeHandle;
}

export function animateLatestItem(
  root: HTMLElement | null,
  selector = "[data-motion-latest='true']",
): AnimeHandle | null {
  if (!root) {
    return null;
  }

  const targets = Array.from(root.querySelectorAll(selector));
  if (targets.length === 0) {
    return null;
  }

  anime.remove(targets);
  if (prefersReducedMotion()) {
    anime.set(targets, { opacity: 1, translateY: 0, scale: 1 });
    return null;
  }

  return anime({
    targets,
    opacity: [0, 1],
    translateY: [motionTokens.distance.sm, 0],
    scale: [0.992, 1],
    duration: motionTokens.duration.tab,
    easing: motionTokens.easing.standard,
  }) as AnimeHandle;
}

export function revealWithin(root: HTMLElement, options: RevealOptions = {}): AnimeHandle | null {
  const {
    selector = "[data-motion-reveal]",
    axis = "y",
    distance = motionTokens.distance.md,
    duration = motionTokens.duration.reveal,
    delay = 0,
    stagger = motionTokens.stagger.normal,
    scaleFrom = 1,
    easing = motionTokens.easing.emphasized,
  } = options;
  const targets = Array.from(root.querySelectorAll(selector));

  if (targets.length === 0) {
    return null;
  }

  anime.remove(targets);
  const axisProp = getAxisProperty(axis);
  if (prefersReducedMotion()) {
    anime.set(targets, {
      opacity: 1,
      translateX: 0,
      translateY: 0,
      scale: 1,
    });
    return null;
  }

  const params: Record<string, unknown> = {
    targets,
    opacity: [0, 1],
    scale: [scaleFrom, 1],
    duration,
    delay: stagger > 0 ? anime.stagger(stagger, { start: delay }) : delay,
    easing,
  };

  if (axisProp) {
    params[axisProp] = [distance, 0];
  }

  return anime(params) as AnimeHandle;
}

function getAxisProperty(axis: MotionAxis): "translateX" | "translateY" | null {
  if (axis === "x") {
    return "translateX";
  }
  if (axis === "y") {
    return "translateY";
  }
  return null;
}

function stopAnimation(
  animation: AnimeHandle | null,
  targets?: HTMLElement | Element[] | Array<Element | null> | string,
  selector?: string,
): void {
  animation?.pause?.();

  if (!targets) {
    return;
  }

  if (typeof targets === "string") {
    anime.remove(targets);
    return;
  }

  if (Array.isArray(targets)) {
    anime.remove(targets.filter(Boolean));
    return;
  }

  if (selector) {
    anime.remove(Array.from(targets.querySelectorAll(selector)));
    return;
  }

  anime.remove(targets);
}

import {
  motion,
  useReducedMotion,
  type Variants,
} from "motion/react";
import {
  useLayoutEffect,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

interface PageTransitionProps {
  children: ReactNode;
  routeKey: string;
}

interface TransitionOverlayProps {
  transitionKey: string;
}

const pageVariants: Variants = {
  initial: {
    opacity: 0,
    y: 22,
    scale: 1.018,
    filter: "blur(16px)",
  },
  animate: {
    opacity: 1,
    y: 0,
    scale: 1,
    filter: "blur(0px)",
  },
  exit: {
    opacity: 0,
    y: -18,
    scale: 0.982,
    filter: "blur(12px)",
  },
};

const reducedPageVariants: Variants = {
  initial: { opacity: 0.98 },
  animate: { opacity: 1 },
  exit: { opacity: 0.98 },
};

const STAGGER_SELECTOR = [
  "[data-route-stagger]",
  ".room-topbar",
  ".room-alert-stack > *",
  ".room-boot .empty-state",
  ".room-ended-summary",
  ".meeting-stage",
  ".room-control-bar",
  ".room-side-panel",
  ".test-page-header",
  ".test-card",
  ".room-header",
  ".join-card",
  ".participant-list-panel",
  ".transcript-panel",
  ".interpreter-panel",
].join(", ");

export function PageTransition({ children, routeKey }: PageTransitionProps) {
  const shouldReduceMotion = useReducedMotion();

  useRouteContentStagger(routeKey, Boolean(shouldReduceMotion));

  return (
    <motion.div
      className="app-route-view"
      data-route-key={routeKey}
      variants={shouldReduceMotion ? reducedPageVariants : pageVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      transition={{
        duration: shouldReduceMotion ? 0.08 : 0.68,
        ease: [0.16, 1, 0.3, 1],
      }}
    >
      {children}
    </motion.div>
  );
}

export function TransitionOverlay({ transitionKey }: TransitionOverlayProps) {
  const shouldReduceMotion = useReducedMotion();
  const mountedRef = useRef(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (shouldReduceMotion) {
      setVisible(false);
      return;
    }

    if (!mountedRef.current) {
      mountedRef.current = true;
      return;
    }

    setVisible(true);
    const timeout = window.setTimeout(() => setVisible(false), 920);
    return () => window.clearTimeout(timeout);
  }, [shouldReduceMotion, transitionKey]);

  if (shouldReduceMotion || !visible) {
    return null;
  }

  return (
    <motion.div
      key={transitionKey}
      className="route-transition-overlay"
      aria-hidden="true"
      initial={{
        x: "-120%",
        opacity: 0,
        skewX: -10,
      }}
      animate={{
        x: ["-120%", "-8%", "116%"],
        opacity: [0, 0.74, 0],
        skewX: [-10, -7, -10],
      }}
      transition={{
        duration: 0.86,
        times: [0, 0.44, 1],
        ease: [0.22, 1, 0.36, 1],
      }}
    />
  );
}

function useRouteContentStagger(routeKey: string, shouldReduceMotion: boolean) {
  useLayoutEffect(() => {
    if (shouldReduceMotion || typeof window === "undefined") {
      scrollToPageTop();
      return;
    }

    scrollToPageTop();

    let runningAnimations: Animation[] = [];
    let animatedTargets: HTMLElement[] = [];

    const timeout = window.setTimeout(() => {
      const root = document.querySelector<HTMLElement>(
        `.app-route-view[data-route-key="${CSS.escape(routeKey)}"]`,
      );

      if (!root || root.querySelector(".hp-root")) {
        return;
      }

      animatedTargets = getUniqueVisibleTargets(root.querySelectorAll<HTMLElement>(STAGGER_SELECTOR));
      runningAnimations = animatedTargets.map((target, index) => {
        target.style.willChange = "transform, opacity, filter";

        const animation = target.animate(
          [
            {
              opacity: 0,
              transform: "translate3d(0, 18px, 0) scale(0.985)",
              filter: "blur(10px)",
            },
            {
              opacity: 1,
              transform: "translate3d(0, 0, 0) scale(1)",
              filter: "blur(0px)",
            },
          ],
          {
            duration: 620,
            delay: 120 + index * 62,
            easing: "cubic-bezier(0.16, 1, 0.3, 1)",
            fill: "both",
          },
        );

        animation.onfinish = () => {
          target.style.willChange = "";
          target.style.opacity = "";
          target.style.transform = "";
          target.style.filter = "";
        };

        return animation;
      });
    }, 120);

    return () => {
      window.clearTimeout(timeout);
      runningAnimations.forEach((animation) => animation.cancel());
      animatedTargets.forEach((target) => {
        target.style.willChange = "";
        target.style.opacity = "";
        target.style.transform = "";
        target.style.filter = "";
      });
    };
  }, [routeKey, shouldReduceMotion]);
}

function getUniqueVisibleTargets(targets: NodeListOf<HTMLElement>): HTMLElement[] {
  const seen = new Set<HTMLElement>();
  return Array.from(targets).filter((target) => {
    if (
      seen.has(target) ||
      target.closest(".custom-select-menu, .audio-sinks, [data-route-stagger-skip]")
    ) {
      return false;
    }

    seen.add(target);
    return target.getClientRects().length > 0;
  });
}

function scrollToPageTop() {
  window.scrollTo({ top: 0, left: 0, behavior: "auto" });
}

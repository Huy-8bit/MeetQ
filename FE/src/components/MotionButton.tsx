import {
  useEffect,
  type ButtonHTMLAttributes,
  type PointerEvent,
  type FocusEvent,
} from "react";
import {
  animateAttentionPulse,
  useAnimePress,
} from "../lib/motion";

interface MotionButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  attentionKey?: unknown;
  pressDisabled?: boolean;
}

export function MotionButton({
  attentionKey,
  pressDisabled = false,
  disabled = false,
  onPointerDown,
  onPointerUp,
  onPointerCancel,
  onPointerLeave,
  onBlur,
  children,
  ...props
}: MotionButtonProps) {
  const { ref, motionPressHandlers } = useAnimePress<HTMLButtonElement>(
    pressDisabled || disabled,
  );

  useEffect(() => {
    if (!attentionKey) {
      return;
    }

    const animation = animateAttentionPulse(ref.current, !pressDisabled && !disabled);
    return () => animation?.pause?.();
  }, [attentionKey, disabled, pressDisabled, ref]);

  return (
    <button
      {...props}
      ref={ref}
      disabled={disabled}
      onPointerDown={(event: PointerEvent<HTMLButtonElement>) => {
        motionPressHandlers.onPointerDown(event);
        onPointerDown?.(event);
      }}
      onPointerUp={(event: PointerEvent<HTMLButtonElement>) => {
        motionPressHandlers.onPointerUp(event);
        onPointerUp?.(event);
      }}
      onPointerCancel={(event: PointerEvent<HTMLButtonElement>) => {
        motionPressHandlers.onPointerCancel(event);
        onPointerCancel?.(event);
      }}
      onPointerLeave={(event: PointerEvent<HTMLButtonElement>) => {
        motionPressHandlers.onPointerLeave(event);
        onPointerLeave?.(event);
      }}
      onBlur={(event: FocusEvent<HTMLButtonElement>) => {
        motionPressHandlers.onBlur(event);
        onBlur?.(event);
      }}
    >
      {children}
    </button>
  );
}

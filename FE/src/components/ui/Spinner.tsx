export function Spinner({ size = "md", label }: { size?: "md" | "lg"; label?: string }) {
  return (
    <span
      className={size === "lg" ? "spinner spinner--lg" : "spinner"}
      role={label ? "status" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}

export function SkeletonLines({ count = 4 }: { count?: number }) {
  return (
    <div aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <div className="skeleton" key={index} />
      ))}
    </div>
  );
}

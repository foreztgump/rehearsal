"use client";

import { useLayoutEffect, useRef, useState } from "react";

// Sliding-pill segmented control (parity with the v4 mockup `.seg`). The active
// gradient pill animates between options via a transform/width it measures from
// the live button geometry, so it stays correct across font/zoom/responsive
// reflows. Generic over the option value type.

export type SegOption<T extends string> = { label: string; value: T };

export default function SegmentedToggle<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: readonly SegOption<T>[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const btnRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [pill, setPill] = useState<{ left: number; width: number }>({ left: 4, width: 0 });

  const activeIndex = Math.max(0, options.findIndex((o) => o.value === value));

  // Measure the active button and position the pill over it. useLayoutEffect so
  // the pill never paints in the wrong place for a frame.
  useLayoutEffect(() => {
    const btn = btnRefs.current[activeIndex];
    if (!btn) return;
    setPill({ left: btn.offsetLeft, width: btn.offsetWidth });
  }, [activeIndex, options]);

  // Reposition on resize (responsive reflow / font swap).
  useLayoutEffect(() => {
    const onResize = () => {
      const btn = btnRefs.current[activeIndex];
      if (btn) setPill({ left: btn.offsetLeft, width: btn.offsetWidth });
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [activeIndex]);

  return (
    <div ref={containerRef} className="seg" role="group" aria-label={ariaLabel}>
      <span
        className="seg-pill"
        aria-hidden="true"
        style={{ width: `${pill.width}px`, transform: `translateX(${pill.left - 4}px)` }}
      />
      {options.map((opt, i) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            ref={(el) => {
              btnRefs.current[i] = el;
            }}
            type="button"
            className={active ? "on" : undefined}
            aria-pressed={active}
            onClick={() => onChange(opt.value)}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

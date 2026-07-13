"use client";

import type { CSSProperties } from "react";

const GRID_STYLE: CSSProperties = {
  backgroundImage:
    "linear-gradient(to right, var(--border) 1px, transparent 1px), linear-gradient(to bottom, var(--border) 1px, transparent 1px)",
  backgroundSize: "20% 100%, 100% 20%",
};

const Y_AXIS_TICKS = [0, 25, 50, 75, 100] as const;
const X_AXIS_TICKS = [0, 20, 40, 60, 80, 100] as const;

export function EmptyChartGrid({ xLabels = [] }: { xLabels?: string[] }) {
  return (
    <div
      aria-hidden="true"
      className="bg-background/20 relative h-full min-h-0 overflow-hidden rounded-sm border border-border"
    >
      <div className="absolute top-0 right-12 bottom-7 left-0">
        <div className="absolute inset-0 opacity-70" style={GRID_STYLE} />
      </div>

      <div className="absolute top-0 right-0 bottom-7 w-12 border-l border-border">
        {Y_AXIS_TICKS.map((tick) => (
          <span
            key={tick}
            className="absolute right-0 h-px w-2 bg-border"
            style={{ top: `${tick}%` }}
          />
        ))}
      </div>

      <div className="absolute right-12 bottom-0 left-0 h-7 border-t border-border">
        {xLabels.length > 0
          ? xLabels.map((label, index) => (
              <span
                key={`${label}-${index}`}
                className="text-muted-foreground absolute top-1.5 -translate-x-1/2 text-[10px] tabular-nums"
                style={{
                  left:
                    xLabels.length === 1
                      ? "50%"
                      : `${(index / (xLabels.length - 1)) * 100}%`,
                }}
              >
                {label}
              </span>
            ))
          : X_AXIS_TICKS.map((tick) => (
              <span
                key={tick}
                className="absolute top-0 h-2 w-px bg-border"
                style={{ left: `${tick}%` }}
              />
            ))}
      </div>

      <div className="absolute right-0 bottom-0 h-7 w-12 border-t border-l border-border" />
    </div>
  );
}

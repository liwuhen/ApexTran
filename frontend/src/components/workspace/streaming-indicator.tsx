"use client";

import { SparklesIcon } from "lucide-react";

import { Shimmer } from "@/components/ai-elements/shimmer";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export function StreamingIndicator({
  className,
  size = "normal",
}: {
  className?: string;
  size?: "normal" | "sm";
}) {
  const { t } = useI18n();

  return (
    <div className={cn("text-muted-foreground flex items-center gap-1.5", className)}>
      <SparklesIcon
        className={cn(
          "animate-pulse",
          size === "sm" ? "size-3.5" : "size-4",
        )}
      />
      <Shimmer
        duration={1.6}
        spread={2}
        className={cn("font-medium", size === "sm" ? "text-xs" : "text-sm")}
      >
        {t.ext.thinking}
      </Shimmer>
    </div>
  );
}

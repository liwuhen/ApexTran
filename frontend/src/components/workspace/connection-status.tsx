"use client";

import { RotateCwIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useSidebar } from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

type Status = "connecting" | "connected" | "disconnected";

/** 周期性 ping 后端健康检查(经 next.config 代理到 web.py 的 /health),并支持手动重连。 */
function useBackendStatus() {
  const [status, setStatus] = useState<Status>("connecting");
  const [latency, setLatency] = useState<number | null>(null);
  const activeRef = useRef(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const check = useCallback(async () => {
    const started = performance.now();
    const controller = new AbortController();
    const abort = setTimeout(() => controller.abort(), 4000);
    try {
      const res = await fetch("/api/langgraph/health", {
        signal: controller.signal,
        cache: "no-store",
      });
      clearTimeout(abort);
      if (!activeRef.current) return;
      if (res.ok) {
        setStatus("connected");
        setLatency(Math.round(performance.now() - started));
      } else {
        setStatus("disconnected");
        setLatency(null);
      }
    } catch {
      clearTimeout(abort);
      if (!activeRef.current) return;
      setStatus("disconnected");
      setLatency(null);
    }
    clearTimeout(timerRef.current);
    if (activeRef.current) timerRef.current = setTimeout(() => void check(), 12000);
  }, []);

  // 手动重连:立刻显示"连接中"并重新检测。
  const retry = useCallback(() => {
    clearTimeout(timerRef.current);
    setStatus("connecting");
    void check();
  }, [check]);

  useEffect(() => {
    activeRef.current = true;
    void check();
    return () => {
      activeRef.current = false;
      clearTimeout(timerRef.current);
    };
  }, [check]);

  return { status, latency, retry };
}

const STATUS_META: Record<
  Status,
  { dot: string; halo: string; pulse: boolean }
> = {
  connected: { dot: "bg-emerald-500", halo: "bg-emerald-400", pulse: true },
  connecting: { dot: "bg-amber-500", halo: "bg-amber-400", pulse: true },
  disconnected: { dot: "bg-rose-500", halo: "bg-rose-400", pulse: false },
};

export function ConnectionStatus() {
  const { status, latency, retry } = useBackendStatus();
  const { open } = useSidebar();
  const { t } = useI18n();
  const meta = STATUS_META[status];
  const label = t.ext.connection[status];
  const isConnecting = status === "connecting";

  const dot = (
    <span className="relative flex size-2.5 shrink-0 items-center justify-center">
      {meta.pulse && (
        <span
          className={cn(
            "absolute inline-flex size-full animate-ping rounded-full opacity-60",
            meta.halo,
          )}
        />
      )}
      <span
        className={cn(
          "relative inline-flex size-2 rounded-full shadow-[0_0_6px] transition-colors",
          meta.dot,
        )}
      />
    </span>
  );

  const title =
    status === "disconnected"
      ? t.ext.connection.clickToReconnect
      : `${t.ext.connection.backend} ${label}`;

  // 收起态:仅一个发光点(未连接时也可点击重连)。
  if (!open) {
    return (
      <button
        type="button"
        onClick={retry}
        disabled={isConnecting}
        title={title}
        aria-label={title}
        className="hover:bg-sidebar-accent flex h-7 w-full items-center justify-center rounded-md transition-colors"
      >
        {dot}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={retry}
      disabled={isConnecting}
      title={title}
      className="group text-muted-foreground hover:bg-sidebar-accent hover:text-foreground flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors disabled:cursor-default"
    >
      {dot}
      <span className="truncate">{label}</span>
      {status === "connected" && latency != null ? (
        <span className="text-muted-foreground/55 ml-auto font-mono text-[10px] tabular-nums group-hover:hidden">
          {latency}ms
        </span>
      ) : null}
      <RotateCwIcon
        className={cn(
          "ml-auto size-3 shrink-0 transition-opacity",
          isConnecting && "animate-spin",
          // 未连接/连接中常显;已连接时仅悬停显示(替换延迟)
          status === "connected"
            ? "hidden opacity-0 group-hover:inline group-hover:opacity-70"
            : status === "disconnected"
              ? "opacity-70"
              : "opacity-50",
        )}
      />
    </button>
  );
}

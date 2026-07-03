"use client";

import type { Message } from "@langchain/langgraph-sdk";
import {
  CoinsIcon,
  HistoryIcon,
  MessageSquarePlusIcon,
  TrendingDownIcon,
  TrendingUpIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { accumulateUsage, formatTokenCount } from "@/core/messages/usage";
import { useThreads } from "@/core/threads/hooks";
import { titleOfThread } from "@/core/threads/utils";

export default function DashboardPage() {
  const { t } = useI18n();
  const { data: threads } = useThreads();

  useEffect(() => {
    document.title = `${t.sidebar.dashboard} - ${t.pages.appName}`;
  }, [t.sidebar.dashboard, t.pages.appName]);

  // 逐会话统计 token,并汇总。
  const { perThread, total } = useMemo(() => {
    const rows = (threads ?? [])
      .map((th) => {
        const u = accumulateUsage((th.values?.messages ?? []) as Message[]);
        return {
          id: th.thread_id,
          title: titleOfThread(th),
          input: u?.inputTokens ?? 0,
          output: u?.outputTokens ?? 0,
          tokens: u?.totalTokens ?? 0,
        };
      })
      .filter((r) => r.tokens > 0)
      .sort((a, b) => b.tokens - a.tokens);

    const sum = rows.reduce(
      (acc, r) => ({
        input: acc.input + r.input,
        output: acc.output + r.output,
        total: acc.total + r.tokens,
      }),
      { input: 0, output: 0, total: 0 },
    );
    return { perThread: rows, total: sum };
  }, [threads]);

  const topThreads = perThread.slice(0, 8);
  const maxTokens = topThreads[0]?.tokens ?? 0;
  const inputPct = total.total ? (total.input / total.total) * 100 : 0;
  const outputPct = total.total ? (total.output / total.total) * 100 : 0;

  const stats = [
    {
      label: t.ext.dashboard.totalThreads,
      value: String(threads?.length ?? 0),
      icon: HistoryIcon,
    },
    {
      label: t.ext.dashboard.totalTokens,
      value: formatTokenCount(total.total),
      icon: CoinsIcon,
    },
    {
      label: t.ext.dashboard.inputTokens,
      value: formatTokenCount(total.input),
      icon: TrendingUpIcon,
    },
    {
      label: t.ext.dashboard.outputTokens,
      value: formatTokenCount(total.output),
      icon: TrendingDownIcon,
    },
  ];

  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody>
        <ScrollArea className="size-full">
          <div className="mx-auto w-full max-w-(--container-width-lg) p-6">
            <h1 className="text-2xl font-bold">{t.sidebar.dashboard}</h1>
            <p className="text-muted-foreground mt-1 text-sm">
              {t.ext.dashboard.overview}
            </p>

            {/* 统计卡片 */}
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {stats.map((s) => (
                <div
                  key={s.label}
                  className="bg-card flex items-center gap-4 rounded-xl border p-5"
                >
                  <div className="bg-accent text-foreground flex size-10 items-center justify-center rounded-lg">
                    <s.icon className="size-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-2xl font-semibold">
                      {s.value}
                    </div>
                    <div className="text-muted-foreground text-sm">
                      {s.label}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* 输入 / 输出 占比条(始终显示,无数据则为 0) */}
            <div className="bg-card mt-6 rounded-xl border p-5">
              <h2 className="text-sm font-semibold">
                {t.ext.dashboard.ioRatio}
              </h2>
              <div className="bg-muted mt-3 flex h-4 w-full overflow-hidden rounded-full">
                <div
                  className="bg-primary h-full"
                  style={{ width: `${inputPct}%` }}
                />
                <div
                  className="h-full bg-emerald-500"
                  style={{ width: `${outputPct}%` }}
                />
              </div>
              <div className="text-muted-foreground mt-2 flex flex-wrap gap-4 text-xs">
                <span className="flex items-center gap-1.5">
                  <span className="bg-primary inline-block size-2.5 rounded-full" />
                  {t.ext.dashboard.input} {formatTokenCount(total.input)} (
                  {inputPct.toFixed(0)}%)
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block size-2.5 rounded-full bg-emerald-500" />
                  {t.ext.dashboard.output} {formatTokenCount(total.output)} (
                  {outputPct.toFixed(0)}%)
                </span>
              </div>
            </div>

            {/* 各会话 token 柱状图(始终显示,无会话则提示) */}
            <div className="bg-card mt-4 rounded-xl border p-5">
              <h2 className="text-sm font-semibold">
                {t.ext.dashboard.topThreads}
              </h2>
              {topThreads.length === 0 ? (
                <div className="text-muted-foreground mt-3 text-sm">
                  {t.ext.dashboard.noTokenData}
                </div>
              ) : (
                <div className="mt-4 flex flex-col gap-3">
                  {topThreads.map((r) => {
                    const pct = maxTokens ? (r.tokens / maxTokens) * 100 : 0;
                    return (
                      <Link
                        key={r.id}
                        href={`/workspace/chats/${r.id}`}
                        className="group flex items-center gap-3"
                      >
                        <div className="w-40 shrink-0 truncate text-sm group-hover:underline">
                          {r.title}
                        </div>
                        <div className="bg-muted h-3 flex-1 overflow-hidden rounded">
                          <div
                            className="bg-primary h-full rounded transition-all"
                            style={{ width: `${Math.max(pct, 2)}%` }}
                          />
                        </div>
                        <div className="w-16 shrink-0 text-right font-mono text-xs">
                          {formatTokenCount(r.tokens)}
                        </div>
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 快捷入口 */}
            <h2 className="mt-8 text-lg font-semibold">
              {t.ext.dashboard.quickActions}
            </h2>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <Link
                href="/workspace/chats/new"
                className="bg-card hover:bg-accent flex items-center gap-3 rounded-xl border p-5 transition-colors"
              >
                <MessageSquarePlusIcon className="size-5" />
                <span className="font-medium">{t.sidebar.newChat}</span>
              </Link>
              <Link
                href="/workspace/chats"
                className="bg-card hover:bg-accent flex items-center gap-3 rounded-xl border p-5 transition-colors"
              >
                <HistoryIcon className="size-5" />
                <span className="font-medium">{t.sidebar.chats}</span>
              </Link>
            </div>
          </div>
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

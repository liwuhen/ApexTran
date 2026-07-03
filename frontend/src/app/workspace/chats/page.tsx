"use client";

import type { Message } from "@langchain/langgraph-sdk";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useThreads } from "@/core/threads/hooks";
import {
  pathOfThread,
  textOfMessage,
  titleOfThread,
} from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

export default function ChatsPage() {
  const { t } = useI18n();
  const { data: threads } = useThreads();
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    document.title = `${t.pages.chats} - ${t.pages.appName}`;
  }, [t.pages.chats, t.pages.appName]);

  const filteredThreads = useMemo(() => {
    return threads?.filter((thread) => {
      return titleOfThread(thread).toLowerCase().includes(search.toLowerCase());
    });
  }, [threads, search]);

  // 列表就绪且还没选中时,默认选第一个。
  useEffect(() => {
    if (!selectedId && filteredThreads && filteredThreads.length > 0) {
      setSelectedId(filteredThreads[0]?.thread_id ?? null);
    }
  }, [filteredThreads, selectedId]);

  const selectedThread = useMemo(
    () => filteredThreads?.find((x) => x.thread_id === selectedId) ?? null,
    [filteredThreads, selectedId],
  );

  const messages = (selectedThread?.values?.messages ?? []) as Message[];

  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody>
        <div className="flex size-full flex-col">
          <header className="flex shrink-0 items-center justify-center pt-8">
            <Input
              type="search"
              className="h-12 w-full max-w-(--container-width-md) text-xl focus-visible:border-ring/50 focus-visible:ring-ring/20 focus-visible:ring-1"
              placeholder={t.chats.searchChats}
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </header>
          <main className="min-h-0 flex-1">
            <div className="mx-auto flex size-full max-w-(--container-width-lg) gap-4 p-4">
              {/* 左栏:会话历史条目 */}
              <div className="flex w-72 shrink-0 flex-col overflow-hidden rounded-lg border">
                <ScrollArea className="min-h-0 flex-1">
                  {filteredThreads && filteredThreads.length > 0 ? (
                    filteredThreads.map((thread) => {
                      const active = thread.thread_id === selectedId;
                      return (
                        <button
                          key={thread.thread_id}
                          type="button"
                          onClick={() => setSelectedId(thread.thread_id)}
                          className={cn(
                            "hover:bg-accent flex w-full flex-col gap-1 border-b p-3 text-left transition-colors",
                            active && "bg-accent",
                          )}
                        >
                          <div className="truncate text-sm font-medium">
                            {titleOfThread(thread)}
                          </div>
                          {thread.updated_at && (
                            <div className="text-muted-foreground text-xs">
                              {formatTimeAgo(thread.updated_at)}
                            </div>
                          )}
                        </button>
                      );
                    })
                  ) : (
                    <div className="text-muted-foreground p-4 text-sm">
                      {t.ext.chatsHistory.empty}
                    </div>
                  )}
                </ScrollArea>
              </div>

              {/* 右栏:选中会话的内容 */}
              <div className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-lg border">
                {selectedThread ? (
                  <>
                    <header className="flex shrink-0 items-center justify-between gap-2 border-b p-4">
                      <div className="truncate font-medium">
                        {titleOfThread(selectedThread)}
                      </div>
                      <Link
                        href={pathOfThread(selectedThread)}
                        className="text-primary shrink-0 text-sm hover:underline"
                      >
                        {t.ext.chatsHistory.open}
                      </Link>
                    </header>
                    <ScrollArea className="min-h-0 flex-1">
                      <div className="flex flex-col gap-4 p-4">
                        {messages.length === 0 ? (
                          <div className="text-muted-foreground text-sm">
                            {t.ext.chatsHistory.emptyContent}
                          </div>
                        ) : (
                          messages.map((m, i) => {
                            const isHuman = m.type === "human";
                            const text = textOfMessage(m) ?? "";
                            if (!text) return null;
                            return (
                              <div
                                key={m.id ?? i}
                                className={cn(
                                  "max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap",
                                  isHuman
                                    ? "bg-primary text-primary-foreground self-end"
                                    : "bg-muted self-start",
                                )}
                              >
                                {text}
                              </div>
                            );
                          })
                        )}
                      </div>
                    </ScrollArea>
                  </>
                ) : (
                  <div className="text-muted-foreground flex flex-1 items-center justify-center text-sm">
                    {t.ext.chatsHistory.pickOne}
                  </div>
                )}
              </div>
            </div>
          </main>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

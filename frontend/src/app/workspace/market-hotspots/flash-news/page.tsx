"use client";

import { FlameIcon } from "lucide-react";
import { useEffect } from "react";

import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

export default function FlashNewsPage() {
  const { t } = useI18n();

  useEffect(() => {
    document.title = `${t.sidebar.flashNews} - ${t.pages.appName}`;
  }, [t.sidebar.flashNews, t.pages.appName]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody>
        <div className="flex size-full flex-col items-center justify-center gap-3 p-6 text-center">
          <div className="bg-accent text-foreground flex size-14 items-center justify-center rounded-2xl">
            <FlameIcon className="size-7" />
          </div>
          <h1 className="text-2xl font-bold">{t.sidebar.flashNews}</h1>
          <p className="text-muted-foreground text-sm">{t.common.comingSoon}</p>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

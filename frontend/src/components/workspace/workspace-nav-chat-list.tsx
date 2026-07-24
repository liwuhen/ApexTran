"use client";

import {
  BarChart3Icon,
  CandlestickChartIcon,
  CalendarClockIcon,
  ChevronRightIcon,
  FlameIcon,
  GemIcon,
  NewspaperIcon,
  LayoutDashboardIcon,
  SearchIcon,
  SparklesIcon,
  RadioIcon,
  StarIcon,
  ZapIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const isMarketHotspotsPath = pathname.startsWith(
    "/workspace/market-hotspots",
  );
  const isMarketAnalysisPath = pathname.startsWith(
    "/workspace/market-analysis",
  );
  const [marketHotspotsOpen, setMarketHotspotsOpen] = useState(false);
  const [marketAnalysisOpen, setMarketAnalysisOpen] = useState(false);

  useEffect(() => {
    if (isMarketHotspotsPath) {
      setMarketHotspotsOpen(true);
    }
  }, [isMarketHotspotsPath]);

  useEffect(() => {
    if (isMarketAnalysisPath) {
      setMarketAnalysisOpen(true);
    }
  }, [isMarketAnalysisPath]);

  return (
    <SidebarGroup className="pt-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/short-term-trading"}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/short-term-trading"
            >
              <ZapIcon />
              <span>{t.sidebar.shortTermTrading}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/swing-seeking"}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/swing-seeking"
            >
              <SearchIcon />
              <span>{t.sidebar.swingSeeking}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/long-term-value"}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/long-term-value"
            >
              <GemIcon />
              <span>{t.sidebar.longTermValue}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <Collapsible
          open={marketHotspotsOpen}
          onOpenChange={setMarketHotspotsOpen}
          asChild
        >
          <SidebarMenuItem>
            <CollapsibleTrigger asChild>
              <SidebarMenuButton isActive={isMarketHotspotsPath}>
                <FlameIcon />
                <span>{t.sidebar.marketHotspots}</span>
                <ChevronRightIcon
                  className={`ml-auto size-4 transition-transform ${
                    marketHotspotsOpen ? "rotate-90" : ""
                  }`}
                />
              </SidebarMenuButton>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <SidebarMenuSub>
                <SidebarMenuSubItem>
                  <SidebarMenuSubButton
                    isActive={
                      pathname === "/workspace/market-hotspots/stock-headlines"
                    }
                    asChild
                  >
                    <Link href="/workspace/market-hotspots/stock-headlines">
                      <NewspaperIcon />
                      <span>{t.sidebar.stockHotlist}</span>
                    </Link>
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
                <SidebarMenuSubItem>
                  <SidebarMenuSubButton
                    isActive={
                      pathname === "/workspace/market-hotspots/selected-news"
                    }
                    asChild
                  >
                    <Link href="/workspace/market-hotspots/selected-news">
                      <StarIcon />
                      <span>{t.sidebar.selectedNews}</span>
                    </Link>
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
                <SidebarMenuSubItem>
                  <SidebarMenuSubButton
                    isActive={
                      pathname === "/workspace/market-hotspots/flash-news"
                    }
                    asChild
                  >
                    <Link href="/workspace/market-hotspots/flash-news">
                      <RadioIcon />
                      <span>{t.sidebar.flashNews}</span>
                    </Link>
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
              </SidebarMenuSub>
            </CollapsibleContent>
          </SidebarMenuItem>
        </Collapsible>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/ai-analysis"}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/ai-analysis"
            >
              <SparklesIcon />
              <span>{t.sidebar.aiAnalysis}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <Collapsible
          open={marketAnalysisOpen}
          onOpenChange={setMarketAnalysisOpen}
          asChild
        >
          <SidebarMenuItem>
            <CollapsibleTrigger asChild>
              <SidebarMenuButton isActive={isMarketAnalysisPath}>
                <CandlestickChartIcon />
                <span>{t.sidebar.marketAnalysis}</span>
                <ChevronRightIcon
                  className={`ml-auto size-4 transition-transform ${
                    marketAnalysisOpen ? "rotate-90" : ""
                  }`}
                />
              </SidebarMenuButton>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <SidebarMenuSub>
                <SidebarMenuSubItem>
                  <SidebarMenuSubButton
                    isActive={
                      pathname === "/workspace/market-analysis/favorites"
                    }
                    asChild
                  >
                    <Link href="/workspace/market-analysis/favorites">
                      <StarIcon />
                      <span>{t.sidebar.favorites}</span>
                    </Link>
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
                <SidebarMenuSubItem>
                  <SidebarMenuSubButton
                    isActive={
                      pathname === "/workspace/market-analysis/sector-analysis"
                    }
                    asChild
                  >
                    <Link href="/workspace/market-analysis/sector-analysis">
                      <BarChart3Icon />
                      <span>{t.sidebar.sectorAnalysis}</span>
                    </Link>
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
                <SidebarMenuSubItem>
                  <SidebarMenuSubButton
                    isActive={
                      pathname === "/workspace/market-analysis/board-leaders"
                    }
                    asChild
                  >
                    <Link href="/workspace/market-analysis/board-leaders">
                      <FlameIcon />
                      <span>{t.sidebar.boardLeaders}</span>
                    </Link>
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
                <SidebarMenuSubItem>
                  <SidebarMenuSubButton
                    isActive={
                      pathname ===
                      "/workspace/market-analysis/dragon-tiger-board"
                    }
                    asChild
                  >
                    <Link href="/workspace/market-analysis/dragon-tiger-board">
                      <SparklesIcon />
                      <span>{t.sidebar.dragonTigerBoard}</span>
                    </Link>
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
              </SidebarMenuSub>
            </CollapsibleContent>
          </SidebarMenuItem>
        </Collapsible>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/dashboard"}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/dashboard">
              <LayoutDashboardIcon />
              <span>{t.sidebar.dashboard}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/scheduled-tasks"}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/scheduled-tasks"
            >
              <CalendarClockIcon />
              <span>{t.sidebar.scheduledTasks}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarGroup>
  );
}

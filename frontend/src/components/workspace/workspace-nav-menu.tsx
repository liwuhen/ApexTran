"use client";

import {
  BugIcon,
  ChevronsUpDownIcon,
  LogInIcon,
  LogOutIcon,
  Settings2Icon,
  SunIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { authClient } from "@/server/better-auth/client";

import { GithubIcon } from "./github-icon";
import { SettingsDialog } from "./settings";

function NavMenuButtonContent({
  isSidebarOpen,
  session,
}: {
  isSidebarOpen: boolean;
  session: ReturnType<typeof authClient.useSession>["data"];
}) {
  const { t } = useI18n();
  const user = session?.user;
  const displayName = user?.name ?? user?.email ?? t.ext.account.notSignedIn;
  // 随机但稳定的头像:用用户 id/邮箱做种子(DiceBear),加载失败回退到首字母。
  const seed = user?.id ?? user?.email ?? "guest";
  const avatarUrl = `https://api.dicebear.com/9.x/thumbs/svg?seed=${encodeURIComponent(seed)}`;
  const fallback = displayName.charAt(0).toUpperCase();

  const avatar = (
    <Avatar className="ring-sidebar-border size-5 shrink-0 ring-1">
      <AvatarImage src={avatarUrl} alt={displayName} />
      <AvatarFallback className="text-xs">{fallback}</AvatarFallback>
    </Avatar>
  );

  return isSidebarOpen ? (
    <div className="flex w-full items-center gap-2 text-left">
      {avatar}
      <div className="flex min-w-0 flex-1 items-center leading-tight">
        <span className="truncate text-sm font-medium">{displayName}</span>
      </div>
      <ChevronsUpDownIcon className="text-muted-foreground size-4 shrink-0 opacity-70" />
    </div>
  ) : (
    <div className="flex size-full items-center justify-center">{avatar}</div>
  );
}

export function WorkspaceNavMenu() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsDefaultSection, setSettingsDefaultSection] = useState<
    "appearance" | "memory" | "tools" | "skills" | "notification" | "about"
  >("appearance");
  const [mounted, setMounted] = useState(false);
  const { open: isSidebarOpen } = useSidebar();
  const { t } = useI18n();
  const { resolvedTheme, setTheme } = useTheme();
  const router = useRouter();
  const { data: session } = authClient.useSession();

  // 挂载后才渲染 Radix 下拉,避免其自动生成的 id 在 SSR/客户端不一致导致水合报错。
  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <>
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        defaultSection={settingsDefaultSection}
      />
      <SidebarMenu className="w-full">
        <SidebarMenuItem>
          {mounted ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  size="lg"
                  className="border-sidebar-border/60 bg-sidebar-accent/30 hover:bg-sidebar-accent data-[state=open]:bg-sidebar-accent h-10 cursor-pointer rounded-lg border"
                >
                  <NavMenuButtonContent
                    isSidebarOpen={isSidebarOpen}
                    session={session}
                  />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
                align="end"
                side="top"
                sideOffset={4}
              >
                {session?.user ? (
                  <>
                    <DropdownMenuLabel className="font-normal">
                      <div className="truncate text-sm font-medium">
                        {session.user.name || t.ext.account.user}
                      </div>
                      <div className="text-muted-foreground truncate text-xs">
                        {session.user.email}
                      </div>
                    </DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={() => {
                        setSettingsDefaultSection("appearance");
                        setSettingsOpen(true);
                      }}
                    >
                      <Settings2Icon />
                      {t.common.settings}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() =>
                        authClient.signOut({
                          fetchOptions: { onSuccess: () => router.refresh() },
                        })
                      }
                    >
                      <LogOutIcon />
                      {t.ext.account.signOut}
                    </DropdownMenuItem>
                  </>
                ) : (
                  <>
                    <DropdownMenuItem onClick={() => router.push("/login")}>
                      <LogInIcon />
                      {t.ext.account.signInOrUp}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => {
                        setSettingsDefaultSection("appearance");
                        setSettingsOpen(true);
                      }}
                    >
                      <Settings2Icon />
                      {t.common.settings}
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <SidebarMenuButton
              size="lg"
              className="border-sidebar-border/60 bg-sidebar-accent/30 h-10 rounded-lg border"
            >
              <NavMenuButtonContent
                isSidebarOpen={isSidebarOpen}
                session={session}
              />
            </SidebarMenuButton>
          )}
        </SidebarMenuItem>
      </SidebarMenu>
      {/* 设置 / GitHub / 报告 / 主题 / 退出,左对齐放在用户按钮下方 */}
      <div className="flex flex-wrap items-center gap-1 px-1.5 pt-1">
        <button
          type="button"
          aria-label={t.common.settings}
          onClick={() => {
            setSettingsDefaultSection("appearance");
            setSettingsOpen(true);
          }}
          className="text-muted-foreground hover:text-foreground hover:bg-sidebar-accent flex size-8 items-center justify-center rounded-md transition-colors"
        >
          <Settings2Icon className="size-5" />
        </button>
        <a
          href="https://github.com/XLab-Open/ApexTran"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="ApexTran on GitHub"
          className="text-muted-foreground hover:text-foreground hover:bg-sidebar-accent flex size-8 items-center justify-center rounded-md transition-colors"
        >
          <GithubIcon className="size-5" />
        </a>
        <a
          href="https://github.com/XLab-Open/ApexTran/issues"
          target="_blank"
          rel="noopener noreferrer"
          aria-label={t.workspace.reportIssue}
          className="text-muted-foreground hover:text-foreground hover:bg-sidebar-accent flex size-8 items-center justify-center rounded-md transition-colors"
        >
          <BugIcon className="size-5" />
        </a>
        <button
          type="button"
          aria-label="Toggle theme"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          className="text-muted-foreground hover:text-foreground hover:bg-sidebar-accent flex size-8 items-center justify-center rounded-md transition-colors"
        >
          <SunIcon className="size-5" />
        </button>
      </div>
    </>
  );
}

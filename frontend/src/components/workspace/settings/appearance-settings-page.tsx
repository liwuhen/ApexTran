"use client";

import {
  MonitorSmartphoneIcon,
  MoonIcon,
  SunIcon,
  TerminalIcon,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useMemo, type ComponentType, type SVGProps } from "react";

import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

type ThemeId = "system" | "light" | "dark" | "onedark";

export function AppearanceSettingsPage() {
  const { t, locale, changeLocale } = useI18n();
  const { theme, setTheme, systemTheme } = useTheme();
  const [settings, setSettings] = useLocalSettings();
  const currentTheme = (theme ?? "system") as ThemeId;

  const themeOptions = useMemo(
    () => [
      {
        id: "system" as ThemeId,
        label: t.settings.appearance.system,
        description: t.settings.appearance.systemDescription,
        icon: MonitorSmartphoneIcon,
      },
      {
        id: "light" as ThemeId,
        label: t.settings.appearance.light,
        description: t.settings.appearance.lightDescription,
        icon: SunIcon,
      },
      {
        id: "dark" as ThemeId,
        label: t.settings.appearance.dark,
        description: t.settings.appearance.darkDescription,
        icon: MoonIcon,
      },
      {
        id: "onedark" as ThemeId,
        label: t.settings.appearance.onedark,
        description: t.settings.appearance.onedarkDescription,
        icon: TerminalIcon,
      },
    ],
    [
      t.settings.appearance.dark,
      t.settings.appearance.darkDescription,
      t.settings.appearance.light,
      t.settings.appearance.lightDescription,
      t.settings.appearance.onedark,
      t.settings.appearance.onedarkDescription,
      t.settings.appearance.system,
      t.settings.appearance.systemDescription,
    ],
  );

  return (
    <div className="space-y-8">
      <SettingsSection
        title={t.settings.appearance.themeTitle}
        description={t.settings.appearance.themeDescription}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {themeOptions.map((option) => (
            <ThemePreviewCard
              key={option.id}
              icon={option.icon}
              label={option.label}
              description={option.description}
              active={currentTheme === option.id}
              mode={option.id}
              systemTheme={systemTheme}
              onSelect={(value) => setTheme(value)}
            />
          ))}
        </div>
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.ext.appearance.glassTitle}
        description={t.ext.appearance.glassDescription}
      >
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <span className="text-sm font-medium">
              {t.ext.appearance.enableGlass}
            </span>
            <Switch
              checked={settings.appearance.glass}
              onCheckedChange={(checked) =>
                setSettings("appearance", { glass: checked })
              }
            />
          </div>
          {settings.appearance.glass && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span>{t.ext.appearance.surfaceOpacity}</span>
                <span className="text-muted-foreground tabular-nums">
                  {settings.appearance.glassOpacity}%
                </span>
              </div>
              <input
                type="range"
                min={50}
                max={100}
                step={5}
                value={settings.appearance.glassOpacity}
                onChange={(e) =>
                  setSettings("appearance", {
                    glassOpacity: Number(e.target.value),
                  })
                }
                className="accent-primary w-full"
                aria-label={t.ext.appearance.surfaceOpacity}
              />
            </div>
          )}
        </div>
      </SettingsSection>
    </div>
  );
}

function ThemePreviewCard({
  icon: Icon,
  label,
  description,
  active,
  mode,
  systemTheme,
  onSelect,
}: {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  label: string;
  description: string;
  active: boolean;
  mode: ThemeId;
  systemTheme?: string;
  onSelect: (mode: ThemeId) => void;
}) {
  const previewMode =
    mode === "system" ? (systemTheme === "dark" ? "dark" : "light") : mode;
  const isOneDark = previewMode === "onedark";
  const isDarkLike = previewMode === "dark" || isOneDark;
  return (
    <button
      type="button"
      onClick={() => onSelect(mode)}
      className={cn(
        "group flex h-full flex-col gap-3 rounded-lg border p-4 text-left transition-all",
        active
          ? "border-primary ring-primary/30 shadow-sm ring-2"
          : "hover:border-border hover:shadow-sm",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="bg-muted rounded-md p-2">
          <Icon className="size-4" />
        </div>
        <div className="space-y-1">
          <div className="text-sm leading-none font-semibold">{label}</div>
          <p className="text-muted-foreground text-xs leading-snug">
            {description}
          </p>
        </div>
      </div>
      <div
        className={cn(
          "relative overflow-hidden rounded-md border text-xs transition-colors",
          isOneDark
            ? "border-[#2c313a] bg-[#1e222a] text-[#dcdfe4]"
            : previewMode === "dark"
              ? "border-neutral-800 bg-neutral-900 text-neutral-200"
              : "border-slate-200 bg-white text-slate-900",
        )}
      >
        <div className="border-border/50 flex items-center gap-2 border-b px-3 py-2">
          <div
            className={cn(
              "h-2 w-2 rounded-full",
              isOneDark
                ? "bg-[#61afef]"
                : isDarkLike
                  ? "bg-emerald-400"
                  : "bg-emerald-500",
            )}
          />
          <div className="h-2 w-10 rounded-full bg-current/20" />
          <div className="h-2 w-6 rounded-full bg-current/15" />
        </div>
        <div className="grid grid-cols-[1fr_240px] gap-3 px-3 py-3">
          <div className="space-y-2">
            <div className="h-3 w-3/4 rounded-full bg-current/15" />
            <div className="h-3 w-1/2 rounded-full bg-current/10" />
            <div className="h-[90px] rounded-md border border-current/10 bg-current/5" />
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-md bg-current/10" />
              <div className="space-y-2">
                <div className="h-2 w-14 rounded-full bg-current/15" />
                <div className="h-2 w-10 rounded-full bg-current/10" />
              </div>
            </div>
            <div className="flex flex-col gap-1 rounded-md border border-dashed border-current/15 p-2">
              <div className="h-2 w-3/5 rounded-full bg-current/15" />
              <div className="h-2 w-2/5 rounded-full bg-current/10" />
            </div>
          </div>
        </div>
      </div>
    </button>
  );
}

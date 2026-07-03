"use client";

import { BellIcon, SendIcon } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { enUS, isLocale, zhCN, type Locale } from "@/core/i18n";
import { useI18n } from "@/core/i18n/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings } from "@/core/settings";

import { SettingsSection } from "./settings-section";

const languageOptions: { value: Locale; label: string }[] = [
  { value: "en-US", label: enUS.locale.localName },
  { value: "zh-CN", label: zhCN.locale.localName },
];

export function NotificationSettingsPage() {
  const { t, locale, changeLocale } = useI18n();
  const { permission, isSupported, requestPermission, showNotification } =
    useNotification();
  const [settings, setSettings] = useLocalSettings();

  // 没有开关后:浏览器授权即视为启用,清掉可能残留的 enabled=false,
  // 否则 showNotification 会被 "Notification is disabled" 守卫拦住。
  useEffect(() => {
    if (permission === "granted" && !settings.notification.enabled) {
      setSettings("notification", { enabled: true });
    }
  }, [permission, settings.notification.enabled, setSettings]);

  const handleRequestPermission = async () => {
    await requestPermission();
  };

  const handleTestNotification = () => {
    showNotification(t.settings.notification.testTitle, {
      body: t.settings.notification.testBody,
    });
  };

  const languageSection = (
    <SettingsSection
      title={t.settings.appearance.languageTitle}
      description={t.settings.appearance.languageDescription}
    >
      <Select
        value={locale}
        onValueChange={(value) => {
          if (isLocale(value)) {
            changeLocale(value);
          }
        }}
      >
        <SelectTrigger className="w-[220px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {languageOptions.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </SettingsSection>
  );

  if (!isSupported) {
    return (
      <div className="flex flex-col gap-6">
        <SettingsSection
          title={t.settings.notification.title}
          description={t.settings.notification.description}
        >
          <p className="text-muted-foreground text-sm">
            {t.settings.notification.notSupported}
          </p>
        </SettingsSection>
        <Separator />
        {languageSection}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <SettingsSection title={t.settings.notification.title}>
        <div className="flex flex-col gap-4">
        {/* 单独一行:左说明 + 右侧 Send 测试按钮 */}
        <div className="flex items-center justify-between gap-4 rounded-lg border p-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium">
              <BellIcon className="size-4 shrink-0" />
              {t.settings.notification.title}
            </div>
            <div className="text-muted-foreground mt-0.5 text-xs">
              {t.settings.notification.description}
            </div>
          </div>
          {permission === "granted" && (
            <Button
              onClick={handleTestNotification}
              variant="outline"
              size="sm"
              className="shrink-0"
            >
              <SendIcon className="size-4" />
              Send
            </Button>
          )}
        </div>

        {permission === "default" && (
          <Button onClick={handleRequestPermission} variant="default">
            <BellIcon className="mr-2 size-4" />
            {t.settings.notification.requestPermission}
          </Button>
        )}

        {permission === "denied" && (
          <p className="text-muted-foreground rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/50">
            {t.settings.notification.deniedHint}
          </p>
        )}
      </div>
      </SettingsSection>
      <Separator />
      {languageSection}
    </div>
  );
}

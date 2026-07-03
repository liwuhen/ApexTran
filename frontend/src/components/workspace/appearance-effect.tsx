"use client";

import { useEffect } from "react";

import { useLocalSettings } from "@/core/settings";

/**
 * 把外观设置(磨砂效果 + 表面不透明度)应用到 <html>:
 * - 开启时加 `.glass` 类(触发磨砂 CSS)
 * - 通过 `--glass-opacity` 控制表面不透明度(0.5~1)
 */
export function AppearanceEffect() {
  const [settings] = useLocalSettings();
  const { glass, glassOpacity } = settings.appearance;

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("glass", glass);
    root.style.setProperty("--glass-opacity", String(glassOpacity / 100));
  }, [glass, glassOpacity]);

  return null;
}

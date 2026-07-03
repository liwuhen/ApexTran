"use client";

import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

type Particle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
};

/**
 * 浮动粒子光点背景:深色画布上缓慢飘动的光点,距离够近的两点之间连线。
 * 自适应父容器尺寸,支持高 DPI 屏。需放在一个有尺寸的相对/绝对定位容器里。
 */
export function ParticlesNetwork({
  className,
  density = 0.00012,
  color = "rgba(255,255,255,0.85)",
  lineColor = "255,255,255",
  maxDistance = 130,
  speed = 0.3,
}: {
  className?: string;
  /** 每平方像素的粒子数,越大越密 */
  density?: number;
  /** 光点颜色 */
  color?: string;
  /** 连线颜色,"r,g,b" 形式(透明度按距离自动计算) */
  lineColor?: string;
  /** 两点连线的最大距离(px) */
  maxDistance?: number;
  /** 漂浮速度 */
  speed?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const parent = canvas.parentElement;
    let width = 0;
    let height = 0;
    let particles: Particle[] = [];
    let raf = 0;

    function resize() {
      const rect = parent?.getBoundingClientRect();
      width = rect?.width ?? window.innerWidth;
      height = rect?.height ?? window.innerHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas!.width = Math.floor(width * dpr);
      canvas!.height = Math.floor(height * dpr);
      canvas!.style.width = `${width}px`;
      canvas!.style.height = `${height}px`;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);

      const count = Math.max(
        24,
        Math.min(160, Math.floor(width * height * density)),
      );
      particles = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * speed,
        vy: (Math.random() - 0.5) * speed,
      }));
    }

    function step() {
      ctx!.clearRect(0, 0, width, height);

      // 更新位置 + 边界反弹
      for (const p of particles) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0 || p.x > width) p.vx *= -1;
        if (p.y < 0 || p.y > height) p.vy *= -1;
      }

      // 近距离连线
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const a = particles[i];
          const b = particles[j];
          if (!a || !b) continue;
          const dist = Math.hypot(a.x - b.x, a.y - b.y);
          if (dist < maxDistance) {
            const alpha = (1 - dist / maxDistance) * 0.5;
            ctx!.strokeStyle = `rgba(${lineColor},${alpha})`;
            ctx!.lineWidth = 1;
            ctx!.beginPath();
            ctx!.moveTo(a.x, a.y);
            ctx!.lineTo(b.x, b.y);
            ctx!.stroke();
          }
        }
      }

      // 光点
      ctx!.fillStyle = color;
      for (const p of particles) {
        ctx!.beginPath();
        ctx!.arc(p.x, p.y, 1.6, 0, Math.PI * 2);
        ctx!.fill();
      }

      raf = requestAnimationFrame(step);
    }

    resize();
    step();

    const ro = new ResizeObserver(resize);
    if (parent) ro.observe(parent);
    window.addEventListener("resize", resize);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("resize", resize);
    };
  }, [density, color, lineColor, maxDistance, speed]);

  return (
    <canvas
      ref={canvasRef}
      className={cn("absolute inset-0 h-full w-full", className)}
    />
  );
}

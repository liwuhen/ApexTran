"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import { authClient } from "@/server/better-auth/client";

export default function LoginPage() {
  const { t } = useI18n();
  const router = useRouter();
  const [isSignUp, setIsSignUp] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const res = isSignUp
      ? await authClient.signUp.email({ email, password, name })
      : await authClient.signIn.email({ email, password });

    setLoading(false);
    if (res.error) {
      setError(res.error.message ?? t.ext.auth.failed);
      return;
    }
    // 登录/注册成功 → 进工作台
    router.push("/workspace");
    router.refresh();
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a] px-4">
      <form
        onSubmit={handleSubmit}
        className="bg-background w-full max-w-sm space-y-4 rounded-2xl border p-6 shadow-lg"
      >
        <div className="space-y-1 text-center">
          <h1 className="text-2xl font-bold">
            {isSignUp ? t.ext.auth.signUpTitle : t.ext.auth.signInTitle}
          </h1>
          <p className="text-muted-foreground text-sm">{t.ext.auth.tagline}</p>
        </div>

        {isSignUp && (
          <Input
            placeholder={t.ext.auth.namePlaceholder}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        )}
        <Input
          type="email"
          placeholder={t.ext.auth.emailPlaceholder}
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <Input
          type="password"
          placeholder={t.ext.auth.passwordPlaceholder}
          autoComplete={isSignUp ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={8}
          required
        />

        {error && <p className="text-sm text-red-500">{error}</p>}

        <Button type="submit" className="w-full" disabled={loading}>
          {loading
            ? t.ext.auth.processing
            : isSignUp
              ? t.ext.auth.signUp
              : t.ext.auth.signIn}
        </Button>

        <button
          type="button"
          className="text-muted-foreground hover:text-foreground w-full text-center text-sm transition-colors"
          onClick={() => {
            setIsSignUp((v) => !v);
            setError(null);
          }}
        >
          {isSignUp ? t.ext.auth.toLogin : t.ext.auth.toSignUp}
        </button>
      </form>
    </div>
  );
}

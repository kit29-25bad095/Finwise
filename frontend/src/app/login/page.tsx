"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Lock, ArrowRight, ShieldCheck, AlertCircle, Building2 } from "lucide-react";
import { ApiClient } from "@/lib/api";
import { Button } from "@/components/ui/Button";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form State
  const [email, setEmail] = useState("admin@enterprise.internal");
  const [password, setPassword] = useState("Passphrase_Audit_Secure_99#");
  const [fullName, setFullName] = useState("Finance Controller");
  const [tenantName, setTenantName] = useState("Finora Production Enterprise");
  const [tenantSlug, setTenantSlug] = useState("finora-prod");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      if (mode === "login") {
        await ApiClient.login({ email, password });
      } else {
        await ApiClient.register({
          email,
          password,
          full_name: fullName,
          tenant_name: tenantName,
          tenant_slug: tenantSlug,
        });
      }
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Authentication failed. Please verify credentials.");
    } finally {
      setLoading(false);
    }
  };

  const handleDemoAccess = () => {
    // Set presentation session and jump directly to dashboard
    localStorage.setItem("finora_access_token", "demo_token_authenticated");
    localStorage.setItem(
      "finora_user",
      JSON.stringify({
        id: "usr-demo",
        email: "cfo@enterprise.internal",
        full_name: "Chief Financial Officer",
        is_active: true,
        is_superuser: false,
      })
    );
    localStorage.setItem("finora_active_tenant_id", "ten-prod");
    localStorage.setItem("finora_active_role", "FINANCE_MANAGER");
    router.push("/dashboard");
  };

  return (
    <div className="min-h-screen bg-canvas flex flex-col justify-between text-ink-primary font-sans antialiased">
      {/* Top Simple Brand Bar */}
      <header className="h-14 border-b border-border bg-surface px-6 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <div className="w-5 h-5 bg-brand-black text-white flex items-center justify-center text-[11px] font-bold tracking-tighter">
            F
          </div>
          <span className="font-semibold text-sm tracking-tight text-ink-primary">
            Finora
          </span>
        </Link>
        <span className="text-[11px] font-mono text-ink-muted">
          Enterprise Financial Console
        </span>
      </header>

      {/* Center Auth Card */}
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-sm bg-surface border border-border shadow-xs p-6 space-y-5">
          {/* Header */}
          <div className="text-center space-y-1">
            <h1 className="text-base font-semibold text-ink-primary tracking-tight">
              {mode === "login" ? "Sign In to Financial Workspace" : "Register Enterprise Organization"}
            </h1>
            <p className="text-xs text-ink-secondary">
              Deterministic reconciliation & revenue leakage engine.
            </p>
          </div>

          {/* Mode Switcher Tabs */}
          <div className="grid grid-cols-2 border border-border text-xs font-mono">
            <button
              type="button"
              onClick={() => {
                setMode("login");
                setError(null);
              }}
              className={`py-1.5 transition-colors ${
                mode === "login"
                  ? "bg-brand-black text-white font-semibold"
                  : "bg-surface text-ink-secondary hover:bg-hover hover:text-ink-primary"
              }`}
            >
              SIGN IN
            </button>
            <button
              type="button"
              onClick={() => {
                setMode("register");
                setError(null);
              }}
              className={`py-1.5 transition-colors ${
                mode === "register"
                  ? "bg-brand-black text-white font-semibold"
                  : "bg-surface text-ink-secondary hover:bg-hover hover:text-ink-primary"
              }`}
            >
              REGISTER
            </button>
          </div>

          {error && (
            <div className="p-3 bg-[#FEF2F2] border border-[#FECACA] text-[#DC2626] text-xs flex items-start gap-2">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-3.5 text-xs">
            {mode === "register" && (
              <>
                <div className="space-y-1">
                  <label className="text-[11px] font-mono uppercase text-ink-secondary">
                    Full Name
                  </label>
                  <input
                    type="text"
                    required
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    className="w-full px-3 py-1.5 border border-border bg-canvas text-ink-primary focus:outline-none focus:ring-1 focus:ring-ink-primary"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-mono uppercase text-ink-secondary">
                    Organization / Tenant Name
                  </label>
                  <input
                    type="text"
                    required
                    value={tenantName}
                    onChange={(e) => {
                      setTenantName(e.target.value);
                      setTenantSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]/g, "-"));
                    }}
                    className="w-full px-3 py-1.5 border border-border bg-canvas text-ink-primary focus:outline-none focus:ring-1 focus:ring-ink-primary"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-mono uppercase text-ink-secondary">
                    Organization Identifier Slug
                  </label>
                  <input
                    type="text"
                    required
                    value={tenantSlug}
                    onChange={(e) => setTenantSlug(e.target.value)}
                    className="w-full px-3 py-1.5 border border-border bg-canvas text-ink-primary font-mono focus:outline-none focus:ring-1 focus:ring-ink-primary"
                  />
                </div>
              </>
            )}

            <div className="space-y-1">
              <label className="text-[11px] font-mono uppercase text-ink-secondary">
                Work Email Address
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-1.5 border border-border bg-canvas text-ink-primary font-mono focus:outline-none focus:ring-1 focus:ring-ink-primary"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[11px] font-mono uppercase text-ink-secondary">
                Password
              </label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3 py-1.5 border border-border bg-canvas text-ink-primary font-mono focus:outline-none focus:ring-1 focus:ring-ink-primary"
              />
            </div>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              className="w-full mt-2 font-medium"
            >
              {mode === "login" ? "Enter Financial Workspace" : "Provision Organization"}
            </Button>
          </form>

          {/* Quick Demo Access Button */}
          <div className="pt-2 border-t border-border">
            <Button
              type="button"
              variant="secondary"
              size="md"
              onClick={handleDemoAccess}
              className="w-full font-mono text-xs flex items-center justify-center gap-1.5"
            >
              <span>Instant Review Console Access →</span>
            </Button>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="h-12 border-t border-border bg-surface px-6 flex items-center justify-between text-[11px] font-mono text-ink-muted">
        <span>SECURITY: MULTI-TENANT ISOLATION • NUMERIC 18,4</span>
        <span>VERSION: FINORA v1.0</span>
      </footer>
    </div>
  );
}

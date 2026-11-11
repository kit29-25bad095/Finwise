"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Lock, ArrowRight, Building2, User, Mail, ShieldAlert } from "lucide-react";
import { ApiClient } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Login state
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  // Register state
  const [regFullName, setRegFullName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regTenantName, setRegTenantName] = useState("");
  const [regTenantSlug, setRegTenantSlug] = useState("");

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await ApiClient.login({
        email: loginEmail,
        password: loginPassword,
      });
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Failed to authenticate.");
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await ApiClient.register({
        email: regEmail,
        password: regPassword,
        full_name: regFullName,
        tenant_name: regTenantName,
        tenant_slug: regTenantSlug,
      });
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Failed to register organization.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col justify-center items-center px-4 py-12">
      <div className="w-full max-w-md">
        {/* Brand Header */}
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center space-x-3 mb-3">
            <div className="h-10 w-10 rounded-xl bg-primary flex items-center justify-center font-bold text-white shadow-lg shadow-sky-500/20">
              F
            </div>
            <span className="font-semibold text-2xl tracking-tight text-white">Finora</span>
          </Link>
          <p className="text-sm text-slate-400">
            Enterprise Financial Reconciliation & Recovery Console
          </p>
        </div>

        {/* Tab Controls */}
        <div className="flex rounded-xl bg-surface p-1 border border-border mb-6">
          <button
            type="button"
            onClick={() => { setMode("login"); setError(null); }}
            className={`flex-1 py-2 text-xs font-medium rounded-lg transition ${mode === "login" ? "bg-primary text-white shadow-sm" : "text-slate-400 hover:text-white"}`}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => { setMode("register"); setError(null); }}
            className={`flex-1 py-2 text-xs font-medium rounded-lg transition ${mode === "register" ? "bg-primary text-white shadow-sm" : "text-slate-400 hover:text-white"}`}
          >
            Register Organization
          </button>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="mb-6 p-4 rounded-xl border border-rose-800/60 bg-rose-950/40 text-rose-300 text-xs flex items-start space-x-3">
            <ShieldAlert className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
            <div className="leading-relaxed">{error}</div>
          </div>
        )}

        {/* Form Container */}
        <div className="p-8 rounded-2xl border border-border/80 bg-surface/90 shadow-2xl backdrop-blur">
          {mode === "login" ? (
            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Business Email</label>
                <div className="relative">
                  <Mail className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
                  <input
                    type="email"
                    required
                    value={loginEmail}
                    onChange={(e) => setLoginEmail(e.target.value)}
                    placeholder="cfo@company.com"
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-surfaceLight border border-border text-white text-sm focus:outline-none focus:border-primary transition"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Password</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
                  <input
                    type="password"
                    required
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                    placeholder="••••••••••••"
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-surfaceLight border border-border text-white text-sm focus:outline-none focus:border-primary transition"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full mt-4 py-3 rounded-lg bg-primary hover:bg-primary-dark text-white font-medium text-sm transition shadow-md shadow-sky-600/30 flex items-center justify-center space-x-2 disabled:opacity-50"
              >
                <span>{loading ? "Authenticating..." : "Access Console"}</span>
                <ArrowRight className="h-4 w-4" />
              </button>
            </form>
          ) : (
            <form onSubmit={handleRegister} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Full Name</label>
                <div className="relative">
                  <User className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
                  <input
                    type="text"
                    required
                    value={regFullName}
                    onChange={(e) => setRegFullName(e.target.value)}
                    placeholder="Maya Patel"
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-surfaceLight border border-border text-white text-sm focus:outline-none focus:border-primary transition"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Business Email</label>
                <div className="relative">
                  <Mail className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
                  <input
                    type="email"
                    required
                    value={regEmail}
                    onChange={(e) => setRegEmail(e.target.value)}
                    placeholder="maya@brand.com"
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-surfaceLight border border-border text-white text-sm focus:outline-none focus:border-primary transition"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Company / Brand Name</label>
                <div className="relative">
                  <Building2 className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
                  <input
                    type="text"
                    required
                    value={regTenantName}
                    onChange={(e) => {
                      setRegTenantName(e.target.value);
                      if (!regTenantSlug || regTenantSlug === regTenantName.toLowerCase().replace(/[^a-z0-9]/g, "-")) {
                        setRegTenantSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]/g, "-"));
                      }
                    }}
                    placeholder="Acme Retail India"
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-surfaceLight border border-border text-white text-sm focus:outline-none focus:border-primary transition"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Tenant Slug (Unique ID)</label>
                <input
                  type="text"
                  required
                  value={regTenantSlug}
                  onChange={(e) => setRegTenantSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
                  placeholder="acme-retail"
                  className="w-full px-4 py-2.5 rounded-lg bg-surfaceLight border border-border text-white text-sm font-mono focus:outline-none focus:border-primary transition"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Password</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={regPassword}
                    onChange={(e) => setRegPassword(e.target.value)}
                    placeholder="Min 8 characters"
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-surfaceLight border border-border text-white text-sm focus:outline-none focus:border-primary transition"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full mt-4 py-3 rounded-lg bg-primary hover:bg-primary-dark text-white font-medium text-sm transition shadow-md shadow-sky-600/30 flex items-center justify-center space-x-2 disabled:opacity-50"
              >
                <span>{loading ? "Registering..." : "Create Tenant & Sign In"}</span>
                <ArrowRight className="h-4 w-4" />
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

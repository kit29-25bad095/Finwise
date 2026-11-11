"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ShieldCheck, ArrowRight, Activity, Database, CheckCircle2, Lock } from "lucide-react";
import { ApiClient } from "@/lib/api";

export default function Home() {
  const [healthStatus, setHealthStatus] = useState<{ status: string; database: string } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    ApiClient.checkHealth()
      .then((data) => {
        setHealthStatus(data);
        setLoading(false);
      })
      .catch(() => {
        setHealthStatus({ status: "OFFLINE", database: "CONNECTING..." });
        setLoading(false);
      });
  }, []);

  return (
    <main className="min-h-screen bg-background flex flex-col justify-between">
      {/* Top Header */}
      <header className="border-b border-border/40 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center font-bold text-white shadow-lg shadow-sky-500/20">
            F
          </div>
          <div>
            <span className="font-semibold text-lg tracking-tight text-white">Finora</span>
            <span className="ml-2 text-xs uppercase px-2 py-0.5 rounded bg-sky-950 text-sky-400 border border-sky-800">
              Phase 1 Core
            </span>
          </div>
        </div>

        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2 text-xs">
            <span className="relative flex h-2 w-2">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${healthStatus?.status === "ONLINE" ? "bg-emerald-400" : "bg-amber-400"} opacity-75`}></span>
              <span className={`relative inline-flex rounded-full h-2 w-2 ${healthStatus?.status === "ONLINE" ? "bg-emerald-500" : "bg-amber-500"}`}></span>
            </span>
            <span className="text-slate-400">
              Backend: {loading ? "Probing..." : healthStatus?.status || "OFFLINE"}
            </span>
          </div>
          <Link
            href="/login"
            className="px-4 py-2 rounded-lg bg-primary hover:bg-primary-dark text-white text-sm font-medium transition shadow-md shadow-sky-600/20 flex items-center space-x-1"
          >
            <span>Console Access</span>
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </header>

      {/* Hero Content */}
      <section className="max-w-5xl mx-auto px-6 py-16 text-center">
        <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full border border-sky-800/60 bg-sky-950/40 text-xs text-sky-300 mb-6">
          <ShieldCheck className="h-3.5 w-3.5 text-sky-400" />
          <span>Zero Discrepancy Without Traceability • Zero Calculation by AI</span>
        </div>

        <h1 className="text-4xl sm:text-6xl font-bold tracking-tight text-white leading-tight">
          AI-Powered Financial Reconciliation & <br />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-sky-400 via-cyan-300 to-emerald-400">
            Revenue Leakage Engine
          </span>
        </h1>

        <p className="mt-6 text-lg text-slate-400 max-w-2xl mx-auto leading-relaxed">
          Autonomous three-way financial ledger matching across Shopify, Payment Gateways (Razorpay), and Bank Statements for Indian D2C enterprises.
        </p>

        <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link
            href="/login"
            className="w-full sm:w-auto px-6 py-3 rounded-xl bg-primary hover:bg-primary-dark text-white font-medium transition shadow-lg shadow-sky-600/30 flex items-center justify-center space-x-2"
          >
            <span>Launch Merchant Console</span>
            <ArrowRight className="h-4 w-4" />
          </Link>
          <a
            href="http://localhost:8000/api/v1/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="w-full sm:w-auto px-6 py-3 rounded-xl bg-surface hover:bg-surfaceLight border border-border text-slate-300 text-sm font-medium transition flex items-center justify-center space-x-2"
          >
            <Database className="h-4 w-4 text-slate-400" />
            <span>Interactive OpenAPI Specs</span>
          </a>
        </div>

        {/* Phase 1 Verification Grid */}
        <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-6 text-left">
          <div className="p-6 rounded-xl border border-border/50 bg-surface/60 backdrop-blur">
            <div className="h-10 w-10 rounded-lg bg-sky-950/80 border border-sky-800/60 flex items-center justify-center text-sky-400 mb-4">
              <Lock className="h-5 w-5" />
            </div>
            <h3 className="font-semibold text-white text-base">Multi-Tenant Isolation</h3>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">
              Cryptographically verified JWT tenant claims with PostgreSQL Row-Level Security (RLS) policies.
            </p>
          </div>

          <div className="p-6 rounded-xl border border-border/50 bg-surface/60 backdrop-blur">
            <div className="h-10 w-10 rounded-lg bg-emerald-950/80 border border-emerald-800/60 flex items-center justify-center text-emerald-400 mb-4">
              <Activity className="h-5 w-5" />
            </div>
            <h3 className="font-semibold text-white text-base">Configurable Tariffs</h3>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">
              MDR, GST, cutoff times, and tolerance parameters dynamically parameterized per tenant contract.
            </p>
          </div>

          <div className="p-6 rounded-xl border border-border/50 bg-surface/60 backdrop-blur">
            <div className="h-10 w-10 rounded-lg bg-cyan-950/80 border border-cyan-800/60 flex items-center justify-center text-cyan-400 mb-4">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <h3 className="font-semibold text-white text-base">Arbitrary Precision</h3>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">
              Zero floating-point arithmetic. Python Decimal and NUMERIC(18, 4) database storage.
            </p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border/40 px-6 py-6 text-center text-xs text-slate-500">
        Finora Engine v1.0.0 • Phase 1 Scaffolding Complete • Indian D2C Financial Intelligence
      </footer>
    </main>
  );
}

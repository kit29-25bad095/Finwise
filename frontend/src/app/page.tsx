"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ShieldCheck,
  CheckCircle2,
  FileSpreadsheet,
  Lock,
  ArrowUpRight,
  Database,
  GitCompare,
} from "lucide-react";
import { ApiClient } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";

export default function HomePage() {
  const [healthStatus, setHealthStatus] = useState<{ status: string; database: string } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    ApiClient.checkHealth()
      .then((data) => {
        setHealthStatus(data);
        setLoading(false);
      })
      .catch(() => {
        setHealthStatus({ status: "STANDALONE_DEV", database: "LOCAL" });
        setLoading(false);
      });
  }, []);

  return (
    <div className="min-h-screen bg-canvas text-ink-primary flex flex-col justify-between font-sans antialiased selection:bg-[#E4E4E7]">
      {/* Top Editorial Utility Header */}
      <header className="h-14 border-b border-border bg-surface px-6 flex items-center justify-between sticky top-0 z-30">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2">
            <div className="w-5 h-5 bg-brand-black text-white flex items-center justify-center text-[11px] font-bold tracking-tighter">
              F
            </div>
            <span className="font-semibold text-sm tracking-tight text-ink-primary">
              Finora
            </span>
          </Link>
          <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 border border-border text-ink-secondary bg-canvas">
            Monochrome Editorial
          </span>
        </div>

        <div className="flex items-center gap-3 text-xs">
          <div className="hidden sm:flex items-center gap-2 font-mono text-[11px] text-ink-secondary">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-zinc-800" />
            <span>Backend: {loading ? "Probing..." : healthStatus?.status || "ONLINE"}</span>
          </div>
          <Link
            href="/dashboard"
            className="h-8 px-3 text-xs font-medium rounded border border-border bg-surface text-ink-primary hover:bg-hover transition-colors flex items-center gap-1.5"
          >
            <span>Merchant Console</span>
            <ArrowRight className="h-3 w-3" />
          </Link>
          <Link
            href="/login"
            className="h-8 px-3 text-xs font-medium rounded bg-[#18181B] text-white hover:bg-[#27272A] transition-colors flex items-center gap-1.5"
          >
            <span>Sign In</span>
          </Link>
        </div>
      </header>

      {/* Main Hero & Architectural Overview */}
      <main className="flex-1 max-w-5xl mx-auto w-full px-6 py-16 space-y-16">
        {/* Editorial Headline */}
        <div className="space-y-4 max-w-3xl">
          <div className="inline-flex items-center gap-2 text-xs font-mono text-ink-secondary border border-border px-2.5 py-1 bg-surface">
            <span className="font-semibold text-ink-primary">FINANCIAL MANDATE:</span>
            <span>Zero Discrepancy Without Traceability • Zero Calculation by AI</span>
          </div>

          <h1 className="text-3xl sm:text-5xl font-semibold tracking-tight text-ink-primary leading-tight">
            AI-Powered Financial Reconciliation & Revenue Leakage Engine.
          </h1>

          <p className="text-sm sm:text-base text-ink-secondary leading-relaxed max-w-2xl">
            Autonomous, deterministic three-way ledger matching across Shopify orders, payment gateways (Razorpay), and bank statements for Indian mid-sized D2C enterprises.
          </p>

          <div className="pt-2 flex flex-wrap items-center gap-3">
            <Link
              href="/dashboard"
              className="h-10 px-5 text-xs font-medium rounded bg-[#18181B] text-white hover:bg-[#27272A] transition-colors flex items-center gap-2"
            >
              <span>Launch Financial Workspace</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              href="/dashboard/reconciliation"
              className="h-10 px-5 text-xs font-medium rounded border border-border bg-surface text-ink-primary hover:bg-hover transition-colors flex items-center gap-2 font-mono"
            >
              <span>Explore Reconciliation Ledger →</span>
            </Link>
          </div>
        </div>

        {/* Core Principles Grid */}
        <div className="border border-border bg-surface divide-y sm:divide-y-0 sm:divide-x divide-border grid grid-cols-1 sm:grid-cols-3">
          <div className="p-6 space-y-2">
            <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
              MANDATE 01
            </div>
            <h2 className="text-xs font-semibold text-ink-primary">
              Traceability & Provenance
            </h2>
            <p className="text-xs text-ink-secondary leading-relaxed">
              Every identified variance retains cryptographic provenance back to SHA-256 source file checksums and ledger row indices.
            </p>
          </div>

          <div className="p-6 space-y-2">
            <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
              MANDATE 02
            </div>
            <h2 className="text-xs font-semibold text-ink-primary">
              Evidence Before Claims
            </h2>
            <p className="text-xs text-ink-secondary leading-relaxed">
              Suspected discrepancies are never categorized as confirmed financial losses without contractual tariff and banking substantiation.
            </p>
          </div>

          <div className="p-6 space-y-2">
            <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
              MANDATE 03
            </div>
            <h2 className="text-xs font-semibold text-ink-primary">
              Zero Calculation by AI
            </h2>
            <p className="text-xs text-ink-secondary leading-relaxed">
              100% of financial calculations, MDR tariffs, and allocations are pure deterministic Python Decimals. AI acts strictly as an investigative analyst.
            </p>
          </div>
        </div>

        {/* Live Workspace Preview Matrix */}
        <div className="bg-surface border border-border p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <div>
              <span className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                SYSTEM OF RECORD
              </span>
              <h2 className="text-sm font-semibold text-ink-primary">
                High-Density Ledger Modules
              </h2>
            </div>
            <span className="text-xs font-mono text-ink-muted">
              PostgreSQL NUMERIC(18,4)
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
            <Link
              href="/dashboard"
              className="p-3 border border-border hover:bg-hover transition-colors block"
            >
              <div className="font-semibold text-ink-primary mb-1">Financial Overview</div>
              <p className="text-ink-secondary text-[11px]">8 summary metrics, settlement health, and leakage overview.</p>
            </Link>

            <Link
              href="/dashboard/reconciliation"
              className="p-3 border border-border hover:bg-hover transition-colors block"
            >
              <div className="font-semibold text-ink-primary mb-1">Reconciliation Workspace</div>
              <p className="text-ink-secondary text-[11px]">High-density 44px rows with interactive right-side Audit Drawer.</p>
            </Link>

            <Link
              href="/dashboard/exceptions"
              className="p-3 border border-border hover:bg-hover transition-colors block"
            >
              <div className="font-semibold text-ink-primary mb-1">Exception Management</div>
              <p className="text-ink-secondary text-[11px]">Lifecycle tracking across the four core leakage detectors.</p>
            </Link>

            <Link
              href="/dashboard/data-sources"
              className="p-3 border border-border hover:bg-hover transition-colors block"
            >
              <div className="font-semibold text-ink-primary mb-1">Data Ingestion Wizard</div>
              <p className="text-ink-secondary text-[11px]">8-step multipart parser, DDE formula sanitizer, and column mapper.</p>
            </Link>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-surface px-6 py-6 text-xs text-ink-secondary">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 font-mono text-[11px]">
          <div>
            FINORA — AI-POWERED FINANCIAL RECONCILIATION & REVENUE LEAKAGE ENGINE
          </div>
          <div className="flex items-center gap-4 text-ink-muted">
            <a href="http://localhost:8000/api/v1/docs" target="_blank" rel="noreferrer" className="hover:text-ink-primary">
              OpenAPI Specs
            </a>
            <span>•</span>
            <Link href="/dashboard/settings" className="hover:text-ink-primary">
              Configuration
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

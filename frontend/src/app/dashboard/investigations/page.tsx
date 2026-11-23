"use client";

import React, { useState, useEffect } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ApiClient, AIInvestigationStatus } from "@/lib/api";
import {
  Sparkles,
  ShieldCheck,
  AlertCircle,
  FileText,
  RefreshCw,
  Cpu,
  Key,
  Lock,
  CheckCircle2,
} from "lucide-react";

export default function InvestigationsPage() {
  const [data, setData] = useState<AIInvestigationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAIStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await ApiClient.getAIInvestigations();
      setData(res);
    } catch (err: any) {
      setError(err.message || "Failed to query AI investigation gateway.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAIStatus();
  }, []);

  return (
    <div className="flex flex-col min-h-screen bg-canvas">
      <Topbar title="AI Forensic Investigations" breadcrumb="Financial Intelligence" />

      <main className="p-6 md:p-8 space-y-8 max-w-7xl mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              AI Forensic Investigation Panel
            </h1>
            <p className="text-xs text-ink-secondary mt-0.5">
              Provider-agnostic LLM gateway with strict anti-hallucination citation validation
            </p>
          </div>

          <Button
            onClick={fetchAIStatus}
            variant="outline"
            size="sm"
            disabled={loading}
            className="text-xs font-mono"
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
            Check Provider Status
          </Button>
        </div>

        {/* Provider Status Card */}
        <div className="border border-border bg-surface p-6 space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
            <div className="flex items-center gap-3">
              <div className="p-2 border border-border bg-canvas">
                <Cpu className="h-5 w-5 text-ink-primary" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-ink-primary">
                    Provider: {data?.provider || "GOOGLE_GEMINI"}
                  </h2>
                  <Badge variant={data?.is_configured ? "matched" : "pending"}>
                    {data?.status || "PENDING_CONFIGURATION"}
                  </Badge>
                </div>
                <p className="text-xs text-ink-secondary mt-0.5">
                  Target Model: {data?.model_version || "gemini-2.0-flash / gemini-1.5-pro"}
                </p>
              </div>
            </div>

            <div className="text-right text-xs font-mono">
              <span className="text-ink-muted uppercase text-[10px] block">Investigation Queue</span>
              <span className="font-semibold text-ink-primary">
                {data?.investigations_count || 0} Dossiers Generated
              </span>
            </div>
          </div>

          {/* Pending Configuration Notice (Graceful degraded state) */}
          {!data?.is_configured && (
            <div className="p-5 border border-status-pending-text/30 bg-status-pending-bg space-y-3">
              <div className="flex items-center gap-2 text-status-pending-text font-semibold text-xs">
                <Key className="h-4 w-4" />
                <span>Google Gemini API Integration Pending Configuration</span>
              </div>
              <p className="text-xs text-ink-secondary leading-relaxed font-sans">
                {data?.message ||
                  "Google Gemini API integration is currently pending API key provisioning. AI-assisted forensic dossiers and grounded dispute recovery narratives will activate automatically once the GEMINI_API_KEY environment variable is configured."}
              </p>
              <div className="pt-2 border-t border-border/50 text-[11px] font-mono text-ink-muted">
                Core deterministic reconciliation, fee overcharge detection, and bounded knapsack matching operate 100% locally without external AI dependency.
              </div>
            </div>
          )}
        </div>

        {/* AI Governance & Anti-Hallucination Architecture */}
        <div className="border border-border bg-surface p-6 space-y-4">
          <h2 className="text-xs font-mono uppercase tracking-wider text-ink-muted">
            Strict AI Governance & Zero Financial Delegation Mandate
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs font-mono">
            <div className="p-4 border border-border bg-canvas space-y-2">
              <div className="flex items-center gap-1.5 font-semibold text-ink-primary">
                <ShieldCheck className="h-4 w-4 text-ink-primary" />
                <span>Zero Math Delegation</span>
              </div>
              <p className="text-ink-secondary text-[11px] font-sans leading-relaxed">
                100% of mathematical allocations, tolerances, and MDR deductions are computed by deterministic Python routines. The AI never calculates financial balances.
              </p>
            </div>

            <div className="p-4 border border-border bg-canvas space-y-2">
              <div className="flex items-center gap-1.5 font-semibold text-ink-primary">
                <Lock className="h-4 w-4 text-ink-primary" />
                <span>PII-Scrubbed Evidence</span>
              </div>
              <p className="text-ink-secondary text-[11px] font-sans leading-relaxed">
                Free-text customer names, order notes, and banking remarks are permanently scrubbed before generating structured evidence bundles.
              </p>
            </div>

            <div className="p-4 border border-border bg-canvas space-y-2">
              <div className="flex items-center gap-1.5 font-semibold text-ink-primary">
                <CheckCircle2 className="h-4 w-4 text-ink-primary" />
                <span>Citation Verification</span>
              </div>
              <p className="text-ink-secondary text-[11px] font-sans leading-relaxed">
                Every generated hypothesis must cite verified database row offsets and UTRs. Unsubstantiated claims are automatically flagged and rejected.
              </p>
            </div>
          </div>
        </div>

        {/* Investigation History Table / Empty State */}
        <div className="border border-border bg-surface p-4 space-y-4">
          <h2 className="text-xs font-mono uppercase tracking-wider text-ink-muted">
            Completed Investigation Dossiers
          </h2>

          <div className="border border-border p-8 text-center space-y-2">
            <FileText className="h-8 w-8 mx-auto text-ink-muted" strokeWidth={1.5} />
            <div className="text-xs font-semibold text-ink-primary font-mono">
              No Fabricated Findings
            </div>
            <p className="text-xs text-ink-secondary max-w-md mx-auto">
              In accordance with Finora Core Financial Principle #3, completed investigations are never simulated or fabricated. AI dossiers will appear here once active.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

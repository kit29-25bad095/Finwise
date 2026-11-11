"use client";

import React from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Sparkles, ShieldCheck, AlertCircle, FileText } from "lucide-react";

export default function InvestigationsPage() {
  const investigations = [
    {
      id: "INV-2026-0041",
      targetRef: "ORD-98422 (pay_Oz91M204Kpq)",
      hypothesis: "Corporate Card interchange surcharge misclassified as domestic consumer card in settlement batch.",
      evidenceCited: ["Schedule B Contract Tariff (1.85%)", "Settlement Batch SETL-20261110-09 (2.15% applied)"],
      antiHallucinationCheck: "PASSED (All cited UTR and Order IDs grounded in PostgreSQL record)",
      status: "COMPLETED",
      timestamp: "12 Nov 2026, 01:45 IST",
    },
    {
      id: "INV-2026-0042",
      targetRef: "ORD-98423 (pay_Oz91M205Zaa)",
      hypothesis: "Settlement hold caused by automated gateway risk check trigger during high-volume campaign.",
      evidenceCited: ["Shopify order capture timestamp", "HDFC bank clearing window gap log"],
      antiHallucinationCheck: "PASSED (Zero invented reference tokens)",
      status: "COMPLETED",
      timestamp: "12 Nov 2026, 02:10 IST",
    },
  ];

  return (
    <>
      <Topbar title="AI Forensic Investigations" breadcrumb="Investigation" />
      <main className="p-6 space-y-6 max-w-7xl mx-auto w-full">
        <div className="border-b border-border pb-4">
          <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
            AI Forensic Investigation Dossiers
          </h1>
          <p className="text-xs text-ink-secondary mt-1">
            Grounded forensic hypotheses with strict anti-hallucination citation validation. Zero financial calculation delegated.
          </p>
        </div>

        <div className="space-y-4">
          {investigations.map((inv) => (
            <div key={inv.id} className="bg-surface border border-border p-5 space-y-3">
              <div className="flex items-center justify-between border-b border-border pb-2.5">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-semibold text-ink-primary">{inv.id}</span>
                  <span className="text-xs font-mono text-ink-muted">Target: {inv.targetRef}</span>
                </div>
                <Badge variant="matched">{inv.status}</Badge>
              </div>

              <div>
                <span className="text-[10px] uppercase font-mono text-ink-muted font-semibold block mb-0.5">
                  ROOT-CAUSE HYPOTHESIS
                </span>
                <p className="text-xs text-ink-primary leading-relaxed">{inv.hypothesis}</p>
              </div>

              <div className="bg-canvas border border-border p-3 space-y-2 text-xs font-mono">
                <div className="text-[10px] uppercase text-ink-muted font-semibold">CITED EVIDENCE SOURCES</div>
                <ul className="list-disc pl-4 space-y-0.5 text-ink-secondary">
                  {inv.evidenceCited.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-border text-[11px] font-mono text-ink-secondary">
                <span className="flex items-center gap-1.5 text-zinc-700">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  {inv.antiHallucinationCheck}
                </span>
                <span className="text-ink-muted">{inv.timestamp}</span>
              </div>
            </div>
          ))}
        </div>
      </main>
    </>
  );
}

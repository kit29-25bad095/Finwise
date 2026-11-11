"use client";

import React, { useState } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { Sliders, CheckCircle2, ShieldAlert } from "lucide-react";
import { ConfirmationDialog } from "@/components/ui/ConfirmationDialog";

export default function SettingsPage() {
  const [cutoffTime, setCutoffTime] = useState("23:00:00");
  const [feeTolerance, setFeeTolerance] = useState("0.05");
  const [knapsackBound, setKnapsackBound] = useState("5");
  const [saved, setSaved] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const handleSave = () => {
    setConfirmOpen(true);
  };

  const handleConfirmSave = (reason: string) => {
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <>
      <Topbar title="Tenant & Financial Settings" breadcrumb="Administration" />
      <main className="p-6 space-y-6 max-w-4xl mx-auto w-full">
        <div className="border-b border-border pb-4">
          <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
            Financial & Invariant Configuration
          </h1>
          <p className="text-xs text-ink-secondary mt-1">
            Configure tenant-specific banking cutoff schedules, fee tolerances, and Knapsack optimization limits.
          </p>
        </div>

        <div className="bg-surface border border-border p-6 space-y-6">
          <div className="space-y-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-muted font-mono">
              FINANCIAL INVARIANT PARAMETERS
            </h2>

            {/* Parameter 1: Cutoff Time */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start border-b border-border pb-4">
              <div>
                <label className="text-xs font-medium text-ink-primary block">
                  Settlement Cutoff Time
                </label>
                <span className="text-[11px] text-ink-secondary block mt-0.5">
                  Gateway daily batch release threshold (IST).
                </span>
              </div>
              <div className="md:col-span-2">
                <input
                  type="text"
                  value={cutoffTime}
                  onChange={(e) => setCutoffTime(e.target.value)}
                  className="w-full max-w-xs px-3 py-1.5 border border-border bg-canvas text-xs font-mono text-ink-primary focus:outline-none"
                />
                <span className="text-[10px] text-ink-muted block mt-1">
                  Default 23:00:00 (Razorpay daily settlement cutoff).
                </span>
              </div>
            </div>

            {/* Parameter 2: Fee Overcharge Tolerance */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start border-b border-border pb-4">
              <div>
                <label className="text-xs font-medium text-ink-primary block">
                  Fee Overcharge Tolerance (₹)
                </label>
                <span className="text-[11px] text-ink-secondary block mt-0.5">
                  Sub-paisa rounding tolerance buffer (ε).
                </span>
              </div>
              <div className="md:col-span-2">
                <input
                  type="text"
                  value={feeTolerance}
                  onChange={(e) => setFeeTolerance(e.target.value)}
                  className="w-full max-w-xs px-3 py-1.5 border border-border bg-canvas text-xs font-mono text-ink-primary focus:outline-none"
                />
                <span className="text-[10px] text-ink-muted block mt-1">
                  Default ₹0.05. Absorbs standard GST round-half-up tax discrepancies.
                </span>
              </div>
            </div>

            {/* Parameter 3: Max Knapsack Bound */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start">
              <div>
                <label className="text-xs font-medium text-ink-primary block">
                  Max Knapsack Bound (N)
                </label>
                <span className="text-[11px] text-ink-secondary block mt-0.5">
                  Maximum transactions in Pass 5 aggregation.
                </span>
              </div>
              <div className="md:col-span-2">
                <input
                  type="number"
                  value={knapsackBound}
                  onChange={(e) => setKnapsackBound(e.target.value)}
                  className="w-full max-w-xs px-3 py-1.5 border border-border bg-canvas text-xs font-mono text-ink-primary focus:outline-none"
                />
                <span className="text-[10px] text-ink-muted block mt-1">
                  Default 5. If valid allocation cannot be established within N &lt;= 5, routes to human review.
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between pt-4 border-t border-border">
            {saved ? (
              <span className="text-xs font-mono text-zinc-700 flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4" />
                Configuration Updated & Logged to Audit Ledger
              </span>
            ) : (
              <span className="text-[11px] text-ink-muted font-mono">
                Requires ADMIN role authorization
              </span>
            )}

            <Button variant="primary" size="sm" onClick={handleSave}>
              Save Configuration
            </Button>
          </div>
        </div>
      </main>

      <ConfirmationDialog
        isOpen={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={handleConfirmSave}
        title="Confirm Financial Parameter Update"
        description="Updating core settlement cutoffs or tolerance thresholds modifies the deterministic evaluation parameters of Detectors 1 and 3."
        confirmLabel="Authorize Parameter Change"
        severity="critical"
      />
    </>
  );
}

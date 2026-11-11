"use client";

import React, { useState } from "react";
import { Download, RefreshCw, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface TopbarProps {
  title: string;
  breadcrumb?: string;
  onRunSync?: () => void;
  onExportReport?: () => void;
}

export function Topbar({
  title,
  breadcrumb = "Finora",
  onRunSync,
  onExportReport,
}: TopbarProps) {
  const [syncing, setSyncing] = useState(false);
  const [syncedRecently, setSyncedRecently] = useState(false);

  const handleSyncClick = async () => {
    setSyncing(true);
    if (onRunSync) {
      await onRunSync();
    } else {
      // Simulate deterministic 3-way reconciliation pass
      await new Promise((resolve) => setTimeout(resolve, 1400));
    }
    setSyncing(false);
    setSyncedRecently(true);
    setTimeout(() => setSyncedRecently(false), 4000);
  };

  const handleExport = () => {
    if (onExportReport) {
      onExportReport();
    } else {
      // Create and trigger simulated CA reconciliation package CSV download
      const csvContent =
        "data:text/csv;charset=utf-8," +
        "Run_ID,Reconciliation_Date,Order_ID,Gateway_Payment_ID,Bank_UTR,Shopify_Gross,Gateway_Capture,Settlement_Net,Bank_Credit,Variance,Status\n" +
        "REC-2026-0042,2026-11-12,ORD-89421,pay_Oz82K194Nal,HDFCR5202611128912,12500.00,12500.00,12205.00,12205.00,0.00,MATCHED_PASS_1\n" +
        "REC-2026-0042,2026-11-12,ORD-89422,pay_Oz82K195Bqm,HDFCR5202611128913,8400.00,8400.00,8201.20,8165.20,-36.00,LEAKAGE_OVERCHARGE\n";
      const encodedUri = encodeURI(csvContent);
      const link = document.createElement("a");
      link.setAttribute("href", encodedUri);
      link.setAttribute("download", `Finora_CA_Reconciliation_Ledger_${new Date().toISOString().substring(0, 10)}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  };

  return (
    <header className="h-14 bg-surface border-b border-border px-6 flex items-center justify-between sticky top-0 z-20">
      {/* Left: Breadcrumbs & Page Context */}
      <div className="flex items-center gap-2 text-xs">
        <span className="text-ink-muted font-mono uppercase text-[11px]">{breadcrumb}</span>
        <span className="text-ink-muted">/</span>
        <h1 className="text-xs font-semibold text-ink-primary tracking-tight">
          {title}
        </h1>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2.5">
        {syncedRecently && (
          <span className="text-[11px] font-mono text-ink-secondary flex items-center gap-1.5 mr-1">
            <CheckCircle2 className="h-3.5 w-3.5 text-zinc-600" />
            Ledger Synchronized
          </span>
        )}

        <Button
          variant="secondary"
          size="sm"
          onClick={handleExport}
          className="flex items-center gap-1.5"
        >
          <Download className="h-3.5 w-3.5 text-ink-secondary" strokeWidth={1.5} />
          <span>Export CA Report</span>
        </Button>

        <Button
          variant="primary"
          size="sm"
          onClick={handleSyncClick}
          loading={syncing}
          className="flex items-center gap-1.5 font-medium"
        >
          <RefreshCw className={cn("h-3.5 w-3.5 text-white", syncing && "animate-spin")} strokeWidth={1.5} />
          <span>Run 3-Way Sync</span>
        </Button>
      </div>
    </header>
  );
}

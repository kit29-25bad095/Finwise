"use client";

import React from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { Download, FileText, CheckCircle2 } from "lucide-react";

export default function ReportsPage() {
  const reports = [
    {
      title: "Statutory CA 3-Way Reconciliation Package (Nov 2026)",
      period: "01 Nov 2026 – 12 Nov 2026",
      format: "CSV + PDF Dossier",
      size: "4.2 MB",
      generatedOn: "12 Nov 2026, 02:30 IST",
    },
    {
      title: "Payment Gateway MDR & GST Leakage Forensic Schedule",
      period: "01 Nov 2026 – 12 Nov 2026",
      format: "XLSX + Signed Summary",
      size: "1.1 MB",
      generatedOn: "12 Nov 2026, 02:15 IST",
    },
    {
      title: "Bank Statement Nodal Settlement Clearing Audit",
      period: "01 Nov 2026 – 12 Nov 2026",
      format: "CSV",
      size: "820 KB",
      generatedOn: "11 Nov 2026, 23:30 IST",
    },
  ];

  const handleDownload = (name: string) => {
    const csvContent = "data:text/csv;charset=utf-8,Reconciliation_Summary_Report\nTotal_GMV,14280500.00\nTotal_Settled,13994890.00\nDiscrepancies,36000.00\n";
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `${name.replace(/\s+/g, "_")}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <>
      <Topbar title="Statutory CA & Forensic Reports" breadcrumb="Data" />
      <main className="p-6 space-y-6 max-w-7xl mx-auto w-full">
        <div className="border-b border-border pb-4">
          <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
            Financial & CA Audit Reports
          </h1>
          <p className="text-xs text-ink-secondary mt-1">
            Export ready-to-file statutory audit packages and forensic leakage schedules for Chartered Accountants.
          </p>
        </div>

        <div className="space-y-3">
          {reports.map((r, i) => (
            <div key={i} className="bg-surface border border-border p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <FileText className="h-5 w-5 text-ink-muted" strokeWidth={1.5} />
                <div>
                  <h2 className="text-xs font-semibold text-ink-primary">{r.title}</h2>
                  <div className="flex items-center gap-3 text-[11px] font-mono text-ink-muted mt-0.5">
                    <span>PERIOD: {r.period}</span>
                    <span>FORMAT: {r.format}</span>
                    <span>GENERATED: {r.generatedOn}</span>
                  </div>
                </div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => handleDownload(r.title)}
                className="flex items-center gap-1.5"
              >
                <Download className="h-3 w-3" />
                <span>Export Package</span>
              </Button>
            </div>
          ))}
        </div>
      </main>
    </>
  );
}

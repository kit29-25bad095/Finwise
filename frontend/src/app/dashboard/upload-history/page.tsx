"use client";

import React from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { FileClock, ShieldCheck } from "lucide-react";

export default function UploadHistoryPage() {
  const uploads = [
    {
      id: "FILE-2026-0012",
      fileName: "hdfc_current_account_nov2026.csv",
      source: "HDFC Bank Statement",
      rows: 420,
      sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      uploadedBy: "finance.manager@finora.internal",
      timestamp: "12 Nov 2026, 02:00 IST",
      status: "INGESTED",
    },
    {
      id: "FILE-2026-0011",
      fileName: "razorpay_settlement_batch_nov2026.csv",
      source: "Razorpay Gateway",
      rows: 320,
      sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
      uploadedBy: "finance.manager@finora.internal",
      timestamp: "11 Nov 2026, 23:10 IST",
      status: "INGESTED",
    },
    {
      id: "FILE-2026-0010",
      fileName: "shopify_orders_nov2026.csv",
      source: "Shopify OMS",
      rows: 4821,
      sha256: "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
      uploadedBy: "finance.manager@finora.internal",
      timestamp: "11 Nov 2026, 22:45 IST",
      status: "INGESTED",
    },
  ];

  return (
    <>
      <Topbar title="Upload History & File Provenance" breadcrumb="Data" />
      <main className="p-6 space-y-6 max-w-7xl mx-auto w-full">
        <div className="border-b border-border pb-4">
          <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
            Upload History & Cryptographic Provenance
          </h1>
          <p className="text-xs text-ink-secondary mt-1">
            Immutable log of all ingested financial raw files with SHA-256 integrity checksums.
          </p>
        </div>

        <div className="bg-surface border border-border overflow-x-auto">
          <table className="w-full text-xs text-left border-collapse">
            <thead>
              <tr className="border-b border-border bg-canvas text-[11px] font-mono text-ink-muted uppercase">
                <th className="py-2.5 px-3">File ID</th>
                <th className="py-2.5 px-3">File Name</th>
                <th className="py-2.5 px-3">Source Adapter</th>
                <th className="py-2.5 px-3 text-center">Row Count</th>
                <th className="py-2.5 px-3">SHA-256 Cryptographic Hash</th>
                <th className="py-2.5 px-3">Uploaded By</th>
                <th className="py-2.5 px-3">Timestamp</th>
                <th className="py-2.5 px-3 text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border font-mono text-[11px]">
              {uploads.map((u) => (
                <tr key={u.id} className="hover:bg-hover/60 h-11">
                  <td className="py-2 px-3 font-medium text-ink-primary">{u.id}</td>
                  <td className="py-2 px-3 text-ink-primary font-sans">{u.fileName}</td>
                  <td className="py-2 px-3 text-ink-secondary font-sans">{u.source}</td>
                  <td className="py-2 px-3 text-center text-ink-primary">{u.rows}</td>
                  <td className="py-2 px-3 text-ink-muted text-[10px] max-w-xs truncate" title={u.sha256}>
                    {u.sha256}
                  </td>
                  <td className="py-2 px-3 text-ink-secondary font-sans text-xs">{u.uploadedBy}</td>
                  <td className="py-2 px-3 text-ink-muted">{u.timestamp}</td>
                  <td className="py-2 px-3 text-center">
                    <Badge variant="matched">{u.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </>
  );
}

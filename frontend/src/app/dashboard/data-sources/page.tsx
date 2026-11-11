"use client";

import React, { useState } from "react";
import {
  Upload,
  FileCheck2,
  AlertTriangle,
  CheckCircle2,
  ArrowRight,
  ArrowLeft,
  Database,
  FileText,
  ShieldCheck,
  RefreshCw,
} from "lucide-react";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { formatINR } from "@/lib/utils";

type Step = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;

export default function DataSourcesPage() {
  const [currentStep, setCurrentStep] = useState<Step>(1);
  const [selectedSource, setSelectedSource] = useState<"SHOPIFY" | "RAZORPAY" | "HDFC">("HDFC");
  const [fileName, setFileName] = useState("HDFC_Current_Account_Nov2026.csv");
  const [fileHash, setFileHash] = useState("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  const [isProcessing, setIsProcessing] = useState(false);

  // Column mapping states
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({
    "Txn Date": "transaction_date",
    "Narration / Description": "narration_raw",
    "Chq/Ref No.": "bank_utr",
    "Withdrawal (Dr)": "withdrawal_amount",
    "Deposit (Cr)": "deposit_amount",
    "Balance": "account_balance",
  });

  const nextStep = () => setCurrentStep((s) => Math.min(s + 1, 8) as Step);
  const prevStep = () => setCurrentStep((s) => Math.max(s - 1, 1) as Step);

  const handleSimulateUpload = () => {
    setIsProcessing(true);
    setTimeout(() => {
      setIsProcessing(false);
      nextStep();
    }, 1000);
  };

  return (
    <>
      <Topbar title="Data Sources & Ingestion" breadcrumb="Data" />

      <main className="p-6 space-y-6 max-w-4xl mx-auto w-full">
        {/* Editorial Header */}
        <div className="border-b border-border pb-4">
          <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
            Data Ingestion Workflow
          </h1>
          <p className="text-xs text-ink-secondary mt-1">
            Deterministic multipart ingestion, DDE formula neutralization, and canonical ledger mapping.
          </p>
        </div>

        {/* Step Indicator Bar */}
        <div className="bg-surface border border-border p-3 flex items-center justify-between text-xs font-mono">
          <span className="text-ink-secondary">
            STEP {currentStep} OF 8:{" "}
            <strong className="text-ink-primary">
              {currentStep === 1 && "Choose Financial Data Source"}
              {currentStep === 2 && "Upload Source CSV File"}
              {currentStep === 3 && "Validate CSV & Inspect Headers"}
              {currentStep === 4 && "Preview Raw Sample Records"}
              {currentStep === 5 && "Map Columns to Canonical Schema"}
              {currentStep === 6 && "Review Ingestion Warnings & Exceptions"}
              {currentStep === 7 && "Authorize Ledger Import"}
              {currentStep === 8 && "Ingestion Verification Summary"}
            </strong>
          </span>
          <span className="text-[11px] text-ink-muted">
            Zero silent record dropping
          </span>
        </div>

        {/* Step Content Container */}
        <div className="bg-surface border border-border p-6 min-h-[380px] flex flex-col justify-between">
          {/* STEP 1: CHOOSE SOURCE */}
          {currentStep === 1 && (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold text-ink-primary">
                Select Source Adapter
              </h2>
              <p className="text-xs text-ink-secondary">
                Finora standardizes heterogeneous vendor formats into a canonical schema with zero floating-point arithmetic.
              </p>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
                <div
                  onClick={() => setSelectedSource("SHOPIFY")}
                  className={`p-4 border cursor-pointer transition-colors ${
                    selectedSource === "SHOPIFY"
                      ? "border-brand-black bg-canvas shadow-xs"
                      : "border-border hover:bg-hover"
                  }`}
                >
                  <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                    OMS PLATFORM
                  </div>
                  <div className="text-sm font-medium text-ink-primary mt-1">
                    Shopify
                  </div>
                  <p className="text-[11px] text-ink-secondary mt-1">
                    Orders export, line items, cancellations, and gross captures.
                  </p>
                </div>

                <div
                  onClick={() => setSelectedSource("RAZORPAY")}
                  className={`p-4 border cursor-pointer transition-colors ${
                    selectedSource === "RAZORPAY"
                      ? "border-brand-black bg-canvas shadow-xs"
                      : "border-border hover:bg-hover"
                  }`}
                >
                  <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                    PAYMENT GATEWAY
                  </div>
                  <div className="text-sm font-medium text-ink-primary mt-1">
                    Razorpay
                  </div>
                  <p className="text-[11px] text-ink-secondary mt-1">
                    Settlement reports, payment IDs, MDR fees, GST, and UTR batches.
                  </p>
                </div>

                <div
                  onClick={() => setSelectedSource("HDFC")}
                  className={`p-4 border cursor-pointer transition-colors ${
                    selectedSource === "HDFC"
                      ? "border-brand-black bg-canvas shadow-xs"
                      : "border-border hover:bg-hover"
                  }`}
                >
                  <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                    PRIMARY BANK
                  </div>
                  <div className="text-sm font-medium text-ink-primary mt-1">
                    HDFC Bank Statement
                  </div>
                  <p className="text-[11px] text-ink-secondary mt-1">
                    Current account CSV, RTGS/NEFT nodal credits, clearing timestamps.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: UPLOAD CSV */}
          {currentStep === 2 && (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold text-ink-primary">
                Upload {selectedSource} CSV Statement
              </h2>
              <div className="border-2 border-dashed border-border p-8 text-center bg-canvas/40 space-y-3">
                <Upload className="h-8 w-8 text-ink-muted mx-auto" strokeWidth={1.5} />
                <div className="text-xs text-ink-primary font-medium">
                  {fileName}
                </div>
                <p className="text-[11px] text-ink-secondary max-w-sm mx-auto">
                  Drag and drop statement file or browse. Streaming multipart sanitizer automatically neutralizes spreadsheet formula injection (=, +, -, @).
                </p>
                <div className="pt-2">
                  <span className="text-[10px] font-mono text-ink-muted">
                    SHA-256: {fileHash}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* STEP 3: VALIDATE HEADERS */}
          {currentStep === 3 && (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold text-ink-primary">
                Validate File Headers & Delimiters
              </h2>
              <p className="text-xs text-ink-secondary">
                File checksum verified. 6 columns detected. 0 formula injection attempts neutralized.
              </p>
              <div className="border border-border divide-y divide-border text-xs font-mono">
                {Object.keys(columnMapping).map((col, i) => (
                  <div key={i} className="p-2.5 flex items-center justify-between bg-canvas/30">
                    <span className="text-ink-primary font-medium">{col}</span>
                    <Badge variant="matched">ASCII VALID</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* STEP 4: PREVIEW RECORDS */}
          {currentStep === 4 && (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold text-ink-primary">
                Preview Sample Raw Records
              </h2>
              <div className="border border-border overflow-x-auto text-[11px] font-mono">
                <table className="w-full border-collapse">
                  <thead>
                    <tr className="bg-canvas border-b border-border text-ink-muted">
                      <th className="p-2 text-left">Txn Date</th>
                      <th className="p-2 text-left">Narration</th>
                      <th className="p-2 text-left">Chq/Ref No.</th>
                      <th className="p-2 text-right">Deposit (Cr)</th>
                      <th className="p-2 text-right">Balance</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    <tr>
                      <td className="p-2 text-ink-primary">10/11/2026</td>
                      <td className="p-2 text-ink-secondary">CMS/RZP/NODAL/SETL-20261110-09</td>
                      <td className="p-2 text-ink-primary">HDFCR5202611110098</td>
                      <td className="p-2 text-right text-ink-primary">12,227.12</td>
                      <td className="p-2 text-right text-ink-secondary">1,48,20,500.00</td>
                    </tr>
                    <tr>
                      <td className="p-2 text-ink-primary">11/11/2026</td>
                      <td className="p-2 text-ink-secondary">CMS/RZP/NODAL/SETL-20261111-01</td>
                      <td className="p-2 text-ink-primary">HDFCR5202611110099</td>
                      <td className="p-2 text-right text-ink-primary">6,064.65</td>
                      <td className="p-2 text-right text-ink-secondary">1,48,26,564.65</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* STEP 5: CANONICAL SCHEMA MAPPING */}
          {currentStep === 5 && (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold text-ink-primary">
                Map Source Columns to Canonical Financial Ledger
              </h2>
              <div className="border border-border divide-y divide-border text-xs font-mono">
                {Object.entries(columnMapping).map(([src, target]) => (
                  <div key={src} className="p-2.5 flex items-center justify-between">
                    <span className="text-ink-secondary">{src}</span>
                    <span className="text-ink-muted">→</span>
                    <span className="text-ink-primary font-semibold">{target}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* STEP 6: VALIDATION EXCEPTIONS */}
          {currentStep === 6 && (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold text-ink-primary">
                Review Validation Exceptions & Warnings
              </h2>
              <div className="border border-border p-4 bg-canvas/40 space-y-2 text-xs">
                <div className="flex items-center gap-2 text-ink-primary font-semibold">
                  <CheckCircle2 className="h-4 w-4 text-zinc-700" />
                  <span>Validation Passed: 0 fatal syntax errors.</span>
                </div>
                <p className="text-ink-secondary">
                  - 420 bank statement deposit rows parsed.
                  <br />- 0 empty narration fields.
                  <br />- All dates verified against RBI 2026 business day calendar.
                </p>
              </div>
            </div>
          )}

          {/* STEP 7: CONFIRM IMPORT */}
          {currentStep === 7 && (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold text-ink-primary">
                Confirm ACID Transaction Ingestion
              </h2>
              <p className="text-xs text-ink-secondary leading-relaxed">
                Importing will register the source file in <code className="font-mono text-ink-primary">raw_files</code> with SHA-256 hash preservation, write 420 canonical transaction records, and trigger automatic Pass 1 deterministic matching.
              </p>
              <div className="p-3 bg-canvas border border-border text-xs font-mono">
                TENANT: <strong>Finora Production Enterprise</strong> | USER: <strong>finance.lead@brand.com</strong>
              </div>
            </div>
          )}

          {/* STEP 8: IMPORT SUMMARY */}
          {currentStep === 8 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-ink-primary">
                <CheckCircle2 className="h-5 w-5 text-zinc-800" />
                <h2 className="text-base font-semibold">
                  Ingestion Successfully Completed
                </h2>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs font-mono pt-2">
                <div className="border border-border p-3 bg-canvas/30">
                  <span className="text-ink-muted text-[10px] block">TOTAL ROWS</span>
                  <span className="text-base font-semibold text-ink-primary">420</span>
                </div>
                <div className="border border-border p-3 bg-canvas/30">
                  <span className="text-ink-muted text-[10px] block">VALID ROWS</span>
                  <span className="text-base font-semibold text-ink-primary">420</span>
                </div>
                <div className="border border-border p-3 bg-canvas/30">
                  <span className="text-ink-muted text-[10px] block">DUPLICATES IGNORED</span>
                  <span className="text-base font-semibold text-ink-primary">0</span>
                </div>
                <div className="border border-border p-3 bg-canvas/30">
                  <span className="text-ink-muted text-[10px] block">WARNINGS</span>
                  <span className="text-base font-semibold text-ink-primary">0</span>
                </div>
                <div className="border border-border p-3 bg-canvas/30 col-span-2">
                  <span className="text-ink-muted text-[10px] block">SOURCE FILE HASH</span>
                  <span className="text-[10px] text-ink-primary truncate block">{fileHash}</span>
                </div>
              </div>
            </div>
          )}

          {/* Workflow Footer Buttons */}
          <div className="flex items-center justify-between pt-6 border-t border-border mt-6">
            <Button
              variant="secondary"
              size="sm"
              onClick={prevStep}
              disabled={currentStep === 1 || currentStep === 8}
              className="flex items-center gap-1"
            >
              <ArrowLeft className="h-3 w-3" />
              <span>Back</span>
            </Button>

            {currentStep < 7 && (
              <Button
                variant="primary"
                size="sm"
                onClick={nextStep}
                className="flex items-center gap-1"
              >
                <span>Continue</span>
                <ArrowRight className="h-3 w-3" />
              </Button>
            )}

            {currentStep === 7 && (
              <Button
                variant="primary"
                size="sm"
                onClick={handleSimulateUpload}
                loading={isProcessing}
                className="flex items-center gap-1"
              >
                <span>Execute Ledger Import</span>
              </Button>
            )}

            {currentStep === 8 && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setCurrentStep(1)}
              >
                Start Another Import
              </Button>
            )}
          </div>
        </div>
      </main>
    </>
  );
}

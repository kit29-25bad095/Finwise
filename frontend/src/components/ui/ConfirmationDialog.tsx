import React, { useState } from "react";
import { AlertCircle, X, ShieldAlert } from "lucide-react";
import { Button } from "./Button";

interface ConfirmationDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<void> | void;
  title: string;
  description: string;
  confirmLabel?: string;
  severity?: "normal" | "critical";
  reviewerEmail?: string;
}

export function ConfirmationDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm Action",
  severity = "normal",
  reviewerEmail = "finance.reviewer@enterprise.internal",
}: ConfirmationDialogProps) {
  const [reason, setReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleConfirm = async () => {
    if (!reason.trim()) {
      setError("A written justification is required for authoritative financial decisions.");
      return;
    }
    setError(null);
    setIsSubmitting(true);
    try {
      await onConfirm(reason);
      setReason("");
      onClose();
    } catch (e: any) {
      setError(e.message || "Failed to execute confirmation.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[1px] p-4">
      <div className="w-full max-w-lg bg-surface border border-border shadow-sm p-6 flex flex-col gap-4">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2.5">
            {severity === "critical" ? (
              <ShieldAlert className="h-5 w-5 text-[#DC2626]" strokeWidth={1.5} />
            ) : (
              <AlertCircle className="h-5 w-5 text-ink-primary" strokeWidth={1.5} />
            )}
            <h3 className="font-semibold text-base text-ink-primary tracking-tight">
              {title}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="text-ink-muted hover:text-ink-primary transition-colors p-1"
          >
            <X className="h-4 w-4" strokeWidth={1.5} />
          </button>
        </div>

        <p className="text-xs text-ink-secondary leading-relaxed">
          {description}
        </p>

        {/* Audit Sign-off attribution */}
        <div className="bg-canvas border border-border p-3 text-[11px] text-ink-secondary flex items-center justify-between font-mono">
          <span>REVIEWER: <strong className="text-ink-primary">{reviewerEmail}</strong></span>
          <span>TIMESTAMP: <strong className="text-ink-primary">{new Date().toISOString().substring(0, 19)}Z</strong></span>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-ink-secondary">
            Financial Justification & Rationale <span className="text-[#DC2626]">*</span>
          </label>
          <textarea
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
              if (error) setError(null);
            }}
            placeholder="Record formal accounting justification (stored in immutable audit ledger)..."
            rows={3}
            className="w-full text-xs p-2.5 border border-border bg-surface text-ink-primary focus:outline-none focus:ring-1 focus:ring-ink-primary placeholder:text-ink-muted resize-none font-sans"
          />
          {error && <span className="text-[11px] text-[#DC2626]">{error}</span>}
        </div>

        <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
          <Button variant="secondary" size="md" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            variant={severity === "critical" ? "danger" : "primary"}
            size="md"
            onClick={handleConfirm}
            loading={isSubmitting}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

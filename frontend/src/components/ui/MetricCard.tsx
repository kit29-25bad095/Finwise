import React from "react";
import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: string;
  subtext?: string;
  isMonetary?: boolean;
  status?: "default" | "leakage" | "pending" | "matched";
  className?: string;
}

export function MetricCard({
  label,
  value,
  subtext,
  isMonetary = false,
  status = "default",
  className,
}: MetricCardProps) {
  const statusColors = {
    default: "text-ink-primary",
    leakage: "text-[#DC2626]",
    pending: "text-[#D97706]",
    matched: "text-ink-primary",
  };

  return (
    <div
      className={cn(
        "bg-surface border border-border p-4 flex flex-col justify-between transition-colors hover:bg-hover/40",
        className
      )}
    >
      <div className="text-[11px] font-medium uppercase tracking-wider text-ink-secondary mb-2 truncate">
        {label}
      </div>
      <div>
        <div
          className={cn(
            "text-2xl font-semibold tracking-tight",
            isMonetary && "font-mono tabular-nums",
            statusColors[status]
          )}
        >
          {value}
        </div>
        {subtext && (
          <div className="mt-1 text-xs text-ink-muted truncate font-normal">
            {subtext}
          </div>
        )}
      </div>
    </div>
  );
}

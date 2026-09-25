import * as React from "react";
import { cn } from "@/lib/utils";

export function Badge({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-edge bg-panel-2 px-2.5 py-0.5 text-xs font-medium text-slate-300",
        className
      )}
      {...props}
    />
  );
}

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-10 w-full rounded-xl border border-edge bg-ink/60 px-3 py-2 text-sm text-slate-100 placeholder:text-mute focus:outline-none focus:border-neon/60 focus:ring-2 focus:ring-neon/20",
        className
      )}
      {...props}
    />
  );
}

export function Select({ className, children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "flex h-10 w-full rounded-xl border border-edge bg-ink/60 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-neon/60",
        className
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label className={cn("mb-1.5 mt-3 block text-xs font-medium uppercase tracking-wide text-mute", className)} {...props} />
  );
}
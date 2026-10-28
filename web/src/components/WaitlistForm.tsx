"use client";

import { useState } from "react";

import { joinWaitlist } from "@/lib/api";

export function WaitlistForm() {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("CA / accounting firm");
  const [volume, setVolume] = useState("10–50");
  const [state, setState] = useState<"idle" | "saving" | "done">("idle");
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setError("Enter a valid email address.");
      return;
    }
    setState("saving");
    setError("");
    try {
      await joinWaitlist(email, role, volume);
      setState("done");
    } catch {
      setState("idle");
      setError("Couldn't save your email. Check your connection and try again.");
    }
  }

  if (state === "done") {
    return (
      <p className="rounded-md border border-rule-strong bg-ok-bg px-4 py-3 text-ok" role="status">
        You're on the list. We'll email {email} when early access opens.
      </p>
    );
  }

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_auto_auto_auto] sm:items-end" noValidate>
      <label className="grid gap-1 text-sm text-ink-soft">
        Work email
        <input
          type="email"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            setError("");
          }}
          placeholder="you@yourfirm.in"
          className="rounded-md border border-rule-strong bg-sheet px-3 py-2.5 text-ink placeholder:text-ink-faint"
          aria-invalid={!!error}
          aria-describedby="waitlist-error"
        />
      </label>
      <label className="grid gap-1 text-sm text-ink-soft">
        You are
        <select value={role} onChange={(e) => setRole(e.target.value)} className="rounded-md border border-rule-strong bg-sheet px-3 py-2.5 text-ink">
          <option>CA / accounting firm</option>
          <option>Accountant at a business</option>
          <option>Business owner</option>
          <option>Tax practitioner</option>
        </select>
      </label>
      <label className="grid gap-1 text-sm text-ink-soft">
        Statements a month
        <select value={volume} onChange={(e) => setVolume(e.target.value)} className="rounded-md border border-rule-strong bg-sheet px-3 py-2.5 text-ink">
          <option>1–10</option>
          <option>10–50</option>
          <option>50–200</option>
          <option>200+</option>
        </select>
      </label>
      <button type="submit" disabled={state === "saving"} className="rounded-md bg-ink px-5 py-2.5 font-semibold text-white hover:bg-[#121c40] disabled:opacity-60">
        {state === "saving" ? "Joining…" : "Join the waitlist"}
      </button>
      <p id="waitlist-error" className="text-sm text-mismatch sm:col-span-4" aria-live="polite">
        {error}
      </p>
    </form>
  );
}

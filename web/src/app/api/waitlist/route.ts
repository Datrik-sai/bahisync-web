import { put } from "@vercel/blob";
import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";

const ROLES = ["CA / accounting firm", "Accountant at a business", "Business owner", "Tax practitioner"];
const VOLUMES = ["1–10", "10–50", "50–200", "200+"];

/** Waitlist sign-ups: one private JSON blob per entry on Vercel; a local file in development. */
export async function POST(request: Request) {
  let body: { email?: unknown; role?: unknown; statements_per_month?: unknown };
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "Send JSON." }, { status: 400 });
  }
  const email = String(body.email ?? "").trim().toLowerCase();
  if (!/^[^\s@]{1,64}@[^\s@]{1,190}\.[a-z]{2,24}$/i.test(email)) {
    return Response.json({ detail: "Enter a valid email address." }, { status: 422 });
  }
  const entry = {
    email,
    role: ROLES.includes(String(body.role)) ? String(body.role) : "",
    statements_per_month: VOLUMES.includes(String(body.statements_per_month)) ? String(body.statements_per_month) : "",
    at: new Date().toISOString(),
  };

  if (process.env.BLOB_READ_WRITE_TOKEN) {
    await put(`waitlist/${entry.at.slice(0, 10)}.json`, JSON.stringify(entry), {
      access: "private",
      addRandomSuffix: true,
      contentType: "application/json",
    });
  } else {
    const dir = path.join(process.cwd(), ".data");
    await mkdir(dir, { recursive: true });
    await appendFile(path.join(dir, "waitlist.jsonl"), JSON.stringify(entry) + "\n");
  }
  return Response.json({ ok: true });
}

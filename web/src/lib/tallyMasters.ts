/**
 * Reads a TallyPrime masters export (List of Accounts / All Masters, XML) in
 * the browser. Nothing is uploaded. Tally often writes these files as UTF-16
 * and includes control-character references (&#4;) that strict XML parsers
 * reject, so the file is decoded by hand and scanned with a tolerant regex.
 */

export type TallyLedger = { name: string; group: string };

export function decodeTallyFile(buf: ArrayBuffer): string {
  const b = new Uint8Array(buf);
  if (b[0] === 0xff && b[1] === 0xfe) return new TextDecoder("utf-16le").decode(b);
  if (b[0] === 0xfe && b[1] === 0xff) return new TextDecoder("utf-16be").decode(b);
  // UTF-16 without a BOM: every other byte of ASCII text is zero.
  if (b.length > 4 && b[1] === 0 && b[3] === 0) return new TextDecoder("utf-16le").decode(b);
  return new TextDecoder("utf-8").decode(b);
}

function unescapeXml(s: string): string {
  return s
    .replace(/&#(\d+);/g, (_, n) => {
      const code = Number(n);
      return code < 32 ? "" : String.fromCodePoint(code);
    })
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => {
      const code = parseInt(h, 16);
      return code < 32 ? "" : String.fromCodePoint(code);
    })
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .trim();
}

export function parseTallyMasters(xml: string): TallyLedger[] {
  const out = new Map<string, TallyLedger>();
  const ledgerRe = /<LEDGER\b([^>]*)>([\s\S]*?)<\/LEDGER>/gi;
  let m: RegExpExecArray | null;
  while ((m = ledgerRe.exec(xml))) {
    const attrs = m[1];
    const body = m[2];
    const attrName = /\bNAME="([^"]*)"/i.exec(attrs)?.[1];
    const listName = /<NAME\.LIST\b[^>]*>\s*<NAME>([\s\S]*?)<\/NAME>/i.exec(body)?.[1];
    const name = unescapeXml(attrName || listName || "");
    if (!name) continue;
    const group = unescapeXml(/<PARENT\b[^>]*>([\s\S]*?)<\/PARENT>/i.exec(body)?.[1] ?? "");
    out.set(name.toLowerCase(), { name, group });
  }
  return [...out.values()].sort((a, b) => a.name.localeCompare(b.name));
}

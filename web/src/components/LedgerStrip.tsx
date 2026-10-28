/** Hero demonstration: statement rows on ruled paper, each ticked against the
 *  running balance and paired with the Tally voucher it becomes. Static data. */

const ROWS = [
  { date: "03/04/26", narr: "IMPS/P2A/700123/ANAND ENTERPRISES", dr: "", cr: "36,400.00", bal: "84,610.00", vch: "Receipt", led: "Anand Enterprises" },
  { date: "04/04/26", narr: "BIL/ONL/TSSPDCL ELECTRICITY/1102938", dr: "3,214.00", cr: "", bal: "81,396.00", vch: "Payment", led: "Electricity Charges" },
  { date: "06/04/26", narr: "ATM WDL/HYDERABAD AMEERPET", dr: "10,000.00", cr: "", bal: "71,396.00", vch: "Contra", led: "Cash" },
  { date: "08/04/26", narr: "GST PAYMENT CBIC CPIN 2604360012", dr: "18,000.00", cr: "", bal: "53,396.00", vch: "Payment", led: "GST Payable" },
];

export function LedgerStrip() {
  return (
    <div className="overflow-hidden rounded-lg border border-rule-strong bg-sheet">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_17rem]">
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[38rem] border-collapse text-[0.82rem]">
            <caption className="sr-only">Sample statement rows checked against the running balance</caption>
            <thead>
              <tr className="border-b border-rule-strong text-left text-ink-soft">
                <th className="py-2.5 pl-4 pr-2 font-semibold">Date</th>
                <th className="px-2 font-semibold">Narration</th>
                <th className="px-2 text-right font-semibold">Withdrawal</th>
                <th className="px-2 text-right font-semibold">Deposit</th>
                <th className="px-2 text-right font-semibold">Balance</th>
                <th className="w-10 pr-4 text-center font-semibold"><span className="sr-only">Balance check</span></th>
              </tr>
            </thead>
            <tbody>
              <tr className="h-10 border-b border-rule text-ink-faint">
                <td className="pl-4 pr-2">01/04/26</td>
                <td className="px-2">Opening balance</td>
                <td />
                <td />
                <td className="amount px-2">48,210.00</td>
                <td />
              </tr>
              {ROWS.map((r, i) => (
                <tr key={r.date} className="h-10 border-b border-rule last:border-b-0">
                  <td className="pl-4 pr-2 text-ink-soft">{r.date}</td>
                  <td className="max-w-[17rem] truncate px-2 font-medium">{r.narr}</td>
                  <td className="amount px-2">{r.dr}</td>
                  <td className="amount px-2">{r.cr}</td>
                  <td className="amount px-2 font-semibold">{r.bal}</td>
                  <td className="pr-4 text-center">
                    <span
                      className="tick inline-flex h-5 w-5 items-center justify-center rounded-full bg-ok-bg text-[0.7rem] font-bold text-ok"
                      style={{ animationDelay: `${450 + i * 380}ms` }}
                      title="Ties to running balance"
                    >
                      ✓
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ol className="border-t border-rule-strong bg-paper/60 text-[0.8rem] lg:border-l lg:border-t-0" aria-label="Tally vouchers created">
          <li className="flex h-[2.6rem] items-center border-b border-rule-strong px-4 font-semibold text-ink-soft">
            Posted to Tally
          </li>
          <li className="h-10 border-b border-rule" aria-hidden />
          {ROWS.map((r, i) => (
            <li
              key={r.date}
              className="voucher flex h-10 items-center justify-between gap-2 border-b border-rule px-4 last:border-b-0"
              style={{ animationDelay: `${600 + i * 380}ms` }}
            >
              <span className="truncate font-medium">{r.led}</span>
              <span className="shrink-0 rounded border border-rule-strong px-1.5 py-0.5 text-[0.7rem] text-ledger">{r.vch}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

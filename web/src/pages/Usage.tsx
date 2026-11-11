import { useEffect, useState } from "react";
import { Activity, Coins, Layers3, RefreshCw } from "lucide-react";
import { api, type UsageCounts, type UsagePeriod, type UsageReport } from "../api";

const periods = [["today", "Today"], ["week", "1 week"], ["month", "1 month"]] as const;
const number = new Intl.NumberFormat();
const dollars = new Intl.NumberFormat("en-US", {style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6});
const tokens = (counts: UsageCounts) => counts.input_tokens + counts.output_tokens;
const cost = (counts: UsageCounts) => counts.calls > 0 && counts.calls === counts.unpriced ? "Unavailable" : dollars.format(counts.usd);

export function Usage() {
  const [period, setPeriod] = useState<UsagePeriod>("week");
  const [revision, refresh] = useState(0);
  const [report, setReport] = useState<UsageReport | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    api.usageReport(period).then(value => { if (active) setReport(value); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [period, revision]);
  function load(next: UsagePeriod) {
    setPeriod(next); setError(false); setReport(null); refresh(r => r + 1);
  }
  return <section className="usage-dashboard">
    <header className="usage-heading"><h2>Workspace usage</h2>
      <div className="usage-tools"><div className="seg" role="group" aria-label="Usage period">
        {periods.map(([value, label]) => <button key={value} aria-pressed={period === value}
          onClick={() => { if (period !== value) load(value); }}>{label}</button>)}
      </div><button className="btn" aria-label="Refresh usage" title="Refresh usage" disabled={!error && !report}
        onClick={() => load(period)}><RefreshCw size={15} /></button></div>
    </header>
    {error ? <p role="alert">Usage is temporarily unavailable. Try refreshing.</p> :
      !report ? <p role="status">Checking usage…</p> : <>
      <div className="usage-metrics">
        <article><Layers3 /><span>Total tokens</span><strong>{number.format(tokens(report.totals))}</strong>
          <small>{number.format(report.totals.input_tokens)} input · {number.format(report.totals.output_tokens)} output</small></article>
        <article><Coins /><span>Estimated cost</span><strong>{cost(report.totals)}</strong>
          <small>{report.totals.unpriced ? number.format(report.totals.unpriced) + " calls without pricing" : "USD · recorded prices"}</small></article>
        <article><Activity /><span>Model calls</span><strong>{number.format(report.totals.calls)}</strong>
          <small>{report.models.length} {report.models.length === 1 ? "model" : "models"} used</small></article>
      </div>
      <UsageChart report={report} period={period} />
      <h3>Usage by model</h3>
      {report.models.length ? <div className="usage-table"><table><thead><tr>
        {["Model", "Calls", "Input tokens", "Output tokens", "Est. USD"].map(label => <th key={label}>{label}</th>)}
      </tr></thead><tbody>{report.models.map(row => <tr key={row.model}><th scope="row">{row.model}</th>
        <td>{number.format(row.calls)}</td><td>{number.format(row.input_tokens)}</td><td>{number.format(row.output_tokens)}</td>
        <td>{cost(row)}{row.unpriced > 0 && row.unpriced < row.calls && <small>priced calls only</small>}</td></tr>)}</tbody></table></div> :
        <p className="muted">Models appear here after their first recorded call.</p>}
    </>}
  </section>;
}

function UsageChart({report, period}: {report: UsageReport; period: UsagePeriod}) {
  const [metric, setMetric] = useState<"Tokens" | "Cost">("Tokens");
  const [index, setIndex] = useState<number | null>(null);
  const currency = metric === "Cost";
  const value = (row: UsageCounts) => currency ? row.usd : tokens(row);
  const max = Math.max(...report.series.map(value), 0);
  const date = new Intl.DateTimeFormat(undefined, period === "today" ?
    {timeZone:"UTC", hour:"2-digit", minute:"2-digit", hourCycle:"h23"} : {timeZone:"UTC", month:"short", day:"numeric"});
  const label = (at: number) => date.format(at * 1000);
  const describe = (row: UsageReport["series"][number]) =>
    label(row.at) + " UTC · " + number.format(row.input_tokens) + " in · " + number.format(row.output_tokens) + " out · " + cost(row);
  return <figure className="usage-chart"><header className="usage-heading"><h3>Activity over time</h3>
    <div className="seg" role="group" aria-label="Chart metric">{(["Tokens","Cost"] as const).map(name =>
      <button aria-pressed={name === metric} key={name} onClick={() => setMetric(name)}>{name}</button>)}</div></header>
    <div className="usage-chart-meta"><span><i />{currency ? "Estimated USD" : "Input tokens"}</span>
      {!currency && <span><i className="output-dot" />Output tokens</span>}<span>UTC</span></div>
    <div className="usage-plot"><div className="usage-scale" aria-hidden="true">
      <span>{max ? currency ? dollars.format(max) : number.format(max) : ""}</span><span>0</span>
    </div><div className="usage-bars">
      {report.series.map((row, i) => <button key={row.at} aria-label={describe(row)} title={describe(row)}
        tabIndex={row.calls ? 0 : -1} onFocus={() => setIndex(i)} onBlur={() => setIndex(null)}
        onPointerEnter={() => setIndex(i)} onPointerLeave={() => setIndex(null)} onClick={() => setIndex(i)}>
        <span className="usage-bar" style={{height: max ? (100 * value(row) / max) + "%" : 0}}>
          {!currency && tokens(row) > 0 && <i style={{height: (100 * row.output_tokens / tokens(row)) + "%"}} />}
        </span>
      </button>)}
      {!report.totals.calls && <span className="usage-empty">No model calls recorded in this period.</span>}
      {currency && report.totals.calls > 0 && report.totals.calls === report.totals.unpriced &&
        <span className="usage-empty">Pricing unavailable for these calls.</span>}
    </div></div>
    <div className="usage-axis">{[0, Math.floor(report.series.length / 2), report.series.length - 1].map(i =>
      report.series[i] && <span key={i}>{label(report.series[i].at)}</span>)}</div>
    <figcaption>{index !== null && report.series[index] ? describe(report.series[index]) :
      period === "today" ? "Hourly activity today" : period === "week" ? "Daily activity over the last 7 days" : "Daily activity over the last 30 days"}</figcaption>
  </figure>;
}

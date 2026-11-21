import {Table,TableHeader,TableBody,TableRow,TableHead,TableCell} from "../components/ui/table";
import {Chart, BarController, BarElement, CategoryScale, LinearScale, LineController, LineElement, PointElement, Tooltip} from "chart.js";
import { useTheme } from "../theme";
import { Skeleton } from "../components/Skeleton";
import { useEffect, useRef, useState } from "react";
import { Activity, ChartColumn, ChartLine, Coins, Layers3, RefreshCw } from "lucide-react";
import { api, type UsageCounts, type UsagePeriod, type UsageReport } from "../api";

Chart.register(BarController, BarElement, CategoryScale, LinearScale, LineController, LineElement, PointElement, Tooltip);

const periods = [["today", "Today"], ["week", "1 week"], ["month", "1 month"]] as const;
const number = new Intl.NumberFormat();
const dollars = new Intl.NumberFormat("en-US", {style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6});
const tokens = (counts: UsageCounts) => counts.input_tokens + counts.output_tokens;
const cost = (counts: UsageCounts) => counts.calls > 0 && counts.calls === counts.unpriced ? "Unavailable" : dollars.format(counts.usd);

type Metric = "Tokens" | "Cost";
type ChartType = "bar" | "line";

export function Usage() {
  const [metric, setMetric] = useState<Metric>("Tokens");
  const [chartType, setChartType] = useState<ChartType>("bar");
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
      !report ? <Skeleton label="Loading usage" shape="chart" /> : <>
      <div className="usage-metrics">
        <article><Layers3 /><span>Total tokens</span><strong>{number.format(tokens(report.totals))}</strong>
          <small>{number.format(report.totals.input_tokens)} input · {number.format(report.totals.output_tokens)} output</small></article>
        <article><Coins /><span>Estimated cost</span><strong>{cost(report.totals)}</strong>
          <small>{report.totals.unpriced ? number.format(report.totals.unpriced) + " calls without pricing" : "USD · recorded prices"}</small></article>
        <article><Activity /><span>Model calls</span><strong>{number.format(report.totals.calls)}</strong>
          <small>{report.models.length} {report.models.length === 1 ? "model" : "models"} used</small></article>
      </div>
      <UsageChart {...{ report, period, metric, setMetric, chartType, setChartType }} />
      <h3>Usage by model</h3>
      {report.models.length ? <div className="usage-table"><Table><TableHeader><TableRow>
        {["Model", "Calls", "Input tokens", "Output tokens", "Est. USD"].map(label => <TableHead key={label}>{label}</TableHead>)}
      </TableRow></TableHeader><TableBody>{report.models.map(row => <TableRow key={row.model}><TableHead scope="row">{row.model}</TableHead>
        <TableCell>{number.format(row.calls)}</TableCell><TableCell>{number.format(row.input_tokens)}</TableCell><TableCell>{number.format(row.output_tokens)}</TableCell>
        <TableCell>{cost(row)}{row.unpriced > 0 && row.unpriced < row.calls && <small>priced calls only</small>}</TableCell></TableRow>)}</TableBody></Table></div> :
        <p className="muted">Models appear here after their first recorded call.</p>}
    </>}
  </section>;
}

function UsageChart({report, period, metric, setMetric, chartType, setChartType}: {
  report: UsageReport; period: UsagePeriod; metric: Metric; setMetric: (metric: Metric) => void;
  chartType: ChartType; setChartType: (type: ChartType) => void;
}) {
  const [theme] = useTheme();
  const canvas = useRef<HTMLCanvasElement>(null);
  const currency = metric === "Cost";
  useEffect(() => {
    if (!canvas.current || !window.ResizeObserver) return;
    const date = new Intl.DateTimeFormat(undefined,period==="today" ?
      {timeZone:"UTC", hour:"2-digit", minute:"2-digit",hourCycle:"h23"} : {timeZone:"UTC",month:"short",day:"numeric"});
    const style = getComputedStyle(canvas.current);
    const color = style.getPropertyValue("--muted").trim();
    const grid = style.getPropertyValue("--line").trim();
    const input = style.getPropertyValue("--green").trim();
    const series = currency ? [{
      label: "Estimated USD", color: input,
      data: report.series.map(row => row.unpriced && row.calls === row.unpriced ? null : row.usd),
    }] : [
      {label: "Input tokens", color: input, data: report.series.map(row => row.input_tokens)},
      {label: "Output tokens", color: "#5f9fc6", data: report.series.map(row => row.output_tokens)},
    ];
    const bars = chartType === "bar";
    const compact = new Intl.NumberFormat(undefined, {notation: "compact"});
    const chart = new Chart(canvas.current, {
      type: chartType,
      data: {
        labels: report.series.map(row => date.format(row.at * 1000)),
        datasets: series.map(({label, color, data}) => ({
          label, data, backgroundColor: color, borderColor: color,
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: {mode: "index", intersect: false},
        datasets: {
          bar: {maxBarThickness: 32, borderSkipped: "bottom", borderRadius: context => {
            const top = currency || context.datasetIndex === 1 || !report.series[context.dataIndex]?.output_tokens;
            return {topLeft: top ? 7 : 0, topRight: top ? 7 : 0, bottomLeft: 0, bottomRight: 0};
          }},
          line: {borderWidth: 2.5, cubicInterpolationMode: "monotone", pointRadius: 2, pointHoverRadius: 5},
        },
        scales: {
          x: {stacked: bars, grid: {display: false}, border: {display: false},
            ticks: {color, maxRotation: 0, maxTicksLimit: 7, padding: 6}},
          y: {stacked: bars, beginAtZero: true, grid: {color: grid, drawTicks: false},
            border: {display: false, dash: [3, 4]}, ticks: {color, maxTicksLimit: 5, padding: 8,
              callback: value => (currency ? "$" : "") + compact.format(Number(value))}},
        },
      },
    });
    return () => chart.destroy();
  }, [report, period, currency, chartType, theme]);
  return <figure className="usage-chart"><header className="usage-heading"><h3>Activity over time</h3>
    <div className="usage-tools">
      <div className="seg" role="group" aria-label="Chart metric">{(["Tokens","Cost"] as const).map(name =>
        <button aria-pressed={name === metric} key={name} onClick={() => setMetric(name)}>{name}</button>)}</div>
      <div className="seg" role="group" aria-label="Chart type">{([["bar", "Bar chart", ChartColumn], ["line", "Line chart", ChartLine]] as const).map(([type, label, Icon]) =>
        <button aria-label={label} title={label} aria-pressed={chartType === type} key={type} onClick={() => setChartType(type)}><Icon aria-hidden="true" /></button>)}</div>
    </div></header>
    <div className="usage-chart-meta"><span><i />{currency ? "Estimated USD" : "Input tokens"}</span>
      {!currency && <span><i className="output-dot" />Output tokens</span>}<span>UTC</span></div>
    <div className="usage-chart-canvas"><canvas ref={canvas} role="img" aria-label={metric+" by "+(period==="today"?"hour":"day")+" in UTC ("+chartType+" chart)"}>
      {report.series.map(row => <span key={row.at}>{new Date(row.at * 1000).toISOString()}: {currency ? cost(row) : number.format(row.input_tokens) + " input, " + number.format(row.output_tokens) + " output"}. </span>)}
    </canvas>
      {!report.totals.calls && <span className="usage-empty">No model calls recorded in this period.</span>}
      {currency && report.totals.calls > 0 && report.totals.calls === report.totals.unpriced &&
        <span className="usage-empty">Pricing unavailable for these calls.</span>}
    </div>
    <figcaption>{period === "today" ? "Hourly activity today" : period === "week" ? "Daily activity over the last 7 days" : "Daily activity over the last 30 days"}</figcaption>
  </figure>;
}

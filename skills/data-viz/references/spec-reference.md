# Spec reference

## Every spec

| Field | Meaning |
| --- | --- |
| `kind` | one of the kinds below |
| `title`, `caption` | optional words, passed through verbatim (sentence case); title wraps to two lines at most |
| `theme` | `light` (default: the lightest brand colour is the ground) or `dark` (the darkest) |
| `colors` | pin a role to a brand token: `ground`, `ink`, `accent`, `muted`, `quiet`, `rule`, `series` |
| `width`, `height` | canvas in px, 200-4096 (default 1600 × 900); type scales from the 1600 × 900 reference |
| `pixelRatio` | 2 (default, crisp on slides) or 1 (exact physical pixels) |
| `out`, `svgOut` | PNG path and optional SVG path under the working directory |
| `data` | per kind, below |

`--out` and `--svg-out` override the spec's paths; `--tokens <tokens.json>` overrides the brand pack.

## Typed dataset (every chart kind except `stat-card`)

```json
"dataset": {
  "fields": [
    { "name": "month", "type": "dimension" },
    { "name": "revenue", "type": "measure", "unit": "$", "precision": 0 },
    { "name": "day", "type": "temporal" }
  ],
  "rows": [ { "month": "Jan", "revenue": 1200, "day": "2026-01-31" } ],
  "nullPolicy": "reject"
}
```

- `unit`: `%`, `×` and `x` attach (`72%`); `$ € £ ¥` lead (`$1,200`); anything else follows a space
  (`34 min`). `precision` is the most decimals shown (trailing zeros dropped).
- `nullPolicy`: `reject` (default), `zero` or `skip`. Nothing is coerced silently.
- `transforms` (up to 12, in order): `filter {field, op: eq|neq|gt|gte|lt|lte, value}`,
  `sort {field, direction}`, `topN {field, count, direction}`, `aggregate {groupBy, field, op:
  sum|mean|median|min|max|count, as}`, `bin {field, binCount, as}`, `normalize {field, as}` (shares
  of the total, in %), `percentChange {field, as}`, `cumulative {field, as}`.
- Gate options: `valueAxis {min, max}` and `partToWhole: true` (percent shares must sum to 100).

## Kinds

**bar**: `x` (dimension), `y` (measure); optional `series` (dimension) and `stack: true`;
`orient: "horizontal"`; `highlight` (a category, or a series name when there is more than one);
`annotate {at, text}` (single series, at most 60 characters). Single-series bars carry their values,
so the value axis is hidden.

**line**: `x`, `y`, optional `series`; past three series, `highlight` names the one that matters.
Lines are labelled at their ends, never with a legend.

**scatter**: `x`, `y` (measures), optional `label` (dimension), `size` (measure, area-scaled),
`highlight` (a label), `xLabel`, `yLabel` (axis names in words).

**heatmap**: `x`, `y` (dimensions), `value` (measure). Cells take one of the brand ramp's steps
(equal-width buckets between the data's min and max, or `valueAxis`) and print their value, so no key
is needed.

**waterfall**: `label` (dimension), `value` (signed measure: each row is a step), `total: true`
and `totalLabel` for the closing bar. Code computes every running total.

**histogram**: `value` (measure), `binCount` (default 10). Code bins and counts.

**sankey**: `source`, `target` (dimensions), `value` (positive measure). Node totals are computed.

**stat-card**: `value` (number), `unit`, `precision`, `label` (what the number counts),
`baseline {value, label}` and `change` (`ratio` default, `percent`, `delta` or `none`). Code writes
the comparison line, for example `"Up from 12 (4×)"` from `{value: 48, baseline: {value: 12, label:
"Up from"}}`.

**cycle**: `contract` whose edges form one loop through every stage (2-8 stages, `flow`, `feedback`,
`return` or `human-loop`); `highlight` (a stage id), `center` (optional words inside the ring),
`expectedTopologyHash`. Stages run clockwise from the top in loop order.

**diagram**: `contract`; `layout` (`elk` default, or `dagre`), `direction` (`right` default,
`down`, `left`, `up`), `groups [{id, label, nodes: [ids]}]` (one level, a node in at most one group),
`highlight` (a node id), `expectedTopologyHash`. Edge kinds: `association` draws a line, every other
kind an arrow; a node may point at itself with `self-loop`.

## Graph contract

```json
"contract": {
  "version": 1,
  "source": "optional note on where the structure came from",
  "nodes": [ { "id": "brief", "label": "Brief" } ],
  "edges": [ { "id": "e1", "from": "brief", "to": "draft", "kind": "flow", "label": "optional" } ]
}
```

Ids match `^[A-Za-z][A-Za-z0-9_-]{0,63}$`; labels up to 160 characters; up to 48 nodes and 96 edges.
Edge kinds: `flow`, `feedback`, `return`, `human-loop`, `self-loop`, `association`. The topology hash
covers ids, labels, endpoints and kinds; `source`, groups, highlight, layout and canvas size do not
change it.

## Receipt (one JSON line)

`chart {datasetHash, sourceHash, rows, transforms}` and `gates[]` for charts; `topology {topologyHash,
nodeCount, edgeCount, layout, scale, strokePx}` for diagrams (`order` for cycles); `computed` (the
stat card's strings, a waterfall's total); `fonts`, `audit {colours, texts}`, `out`, `svgOut`, `png
{width, height, bytes}`.

The SVG names the brand families rather than embedding them: it renders correctly where the brand
fonts are installed (the sandbox, Paper with the brand fonts). Deliver the PNG; keep the SVG for edits.

# Data and diagrams

The mechanics (kinds, specs, gates, the topology contract) are in `data-viz`, and its
[viz-patterns](../../data-viz/references/viz-patterns.md) page has the figure craft. This page is
the doctrine behind them, with its evidence.

A good open reference for everything here is Claus O. Wilke, *Fundamentals of Data Visualization*,
free online at <https://clauswilke.com/dataviz/> (CC BY-NC-ND 4.0).

## Charts: honest first, then clear

| Principle | Evidence | What `data-viz` does about it |
| --- | --- | --- |
| **Proportional ink.** The amount of ink for a value is proportional to the value; a bar that does not start at zero overstates differences | Wilke, chapter 17, "The principle of proportional ink" | Bar, waterfall and histogram axes must include zero, or the render fails |
| **The numbers you were given are the numbers you show.** Reshape with declared transforms, never by editing values | A chart is a claim; the dataset hash is its receipt | Transforms are allowlisted; the output prints the dataset hash |
| **Colour encodes identity only up to a few categories**; past that it is noise. Highlight the one series that matters and quiet the rest | Wilke, chapter 19, "Common pitfalls of color use" | More than three series needs a `highlight` |
| **Colour is never the only signal** | WCAG 2.1 SC 1.4.1 ([color](color.md)) | Label lines and bars directly; carry state in fill or line style too |
| **Small multiples beat one crowded chart** when several groups share an axis | Wilke, chapter 21, "Multi-panel figures" | Two stories are two renders; compose the panels on one still |
| **One unit per value axis** | Two units on one axis invite a false comparison | Enforced |
| **Parts of a whole sum to the whole** | | Shares marked part-to-whole must sum to 100% |
| **Estimated values are labelled as estimates** | Values read off a screenshot are not measurements | Say so in the caption |

## Picking the visual

The question decides the form, not the data's shape:

| The point | Form |
| --- | --- |
| One number, or one before and after | A stat card, not a chart |
| Which is biggest; one bar is the point | A sorted bar chart with that bar highlighted |
| How it changed over time | A line, one series highlighted |
| A trade-off between two measures | A scatter, the one point that matters labelled |
| How quantities split and merge | A sankey |
| A repeating loop | A cycle, not a flow with a long return arrow |
| How a system is built or how work flows | A diagram |

## Diagrams: draw the mechanism

- **Concept first.** A diagram shows the specific mechanism (what flows where, what changes, what
  decides), labelled in words. A box is its label. A generic network of dots and nodes explains
  nothing (`brand-design`, the kill test).
- **Freeze the meaning before the style.** Nodes, edges, directions and labels go in the contract
  first; every restyle after that pins the topology hash so a style change cannot move an arrow
  (`data-viz`).
- **Construction.** Connectors meet shapes on shared coordinates; axis-aligned connectors stay
  straight; return paths are clean computed curves; one arrowhead style per figure; no connector
  crosses text. The brand pack's `diagramConstruction` sets the stroke and arrowhead rules and
  `brand-lint` checks them (`diagram.*`).
- **Connectors, drawn.** The stroke comes from the pack's stroke token, set in CSS
  (`.connector { stroke-width: var(--brand-stroke) }`): a custom property in an SVG presentation
  attribute is ignored and draws a 1 px line. Each connector is one continuous path; every
  arrowhead references one shared `<marker>`, about 4-5 strokes long and close to equilateral, and
  appears only where the flow has a direction. A connector ends exactly on the middle of its node's
  edge (no gap, not the node's centre), continues through a container to the real target, and sits
  in a layer above the cards it joins.
- **Connectors are quieter than the words they join**: a lower-contrast token than the text, so the
  labels lead. When rebuilding a source, match its weights first; a rebuild that reads "messier"
  than the original almost always has heavier strokes.
- **Crisp lines.** An odd-width stroke centred on a whole pixel blurs across two; centre it on a half
  pixel along the axis that crosses the line (`y` on a horizontal run, `x` on a vertical one), and
  an even-width stroke on a whole one.
- **Hierarchy in a diagram** is position and weight before colour: the main path is the straight,
  heavier one; side paths are lighter. The accent marks the one step that matters.
- **Direction is reading direction.** Flows run left to right or top to bottom for left-to-right
  readers; a vertical flow column is centred so fixed-width arrows do not pin to one side.
- **Phone first for social diagrams.** A wide two-row flow is unreadable on a phone: emit a portrait
  twin from the same contract, scaled to fit rather than taller (`brand-design`).

## Restyling a supplied chart or diagram

It is a transformation, not a redesign: every label, value, annotation, grouping and relationship
survives. Write the dataset or contract from the source first; for a raster, inspect every arrowhead
before writing an edge, and ask when an endpoint is ambiguous
([reference transformations](../../brand-design/references/reference-transformations.md)).

## Charts and diagrams in motion

A chart in a film builds once with purpose (a bar rising, a line drawing, a count arriving) and then
holds still long enough to read; a number still moving when the viewer needs to read it is a defect.
The chart is a HyperFrames scene that can embed the `data-viz` SVG (`motion-direction`, techniques).

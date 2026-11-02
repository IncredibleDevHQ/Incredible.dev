# Which visual, and the figure craft

Observations to weigh, not rules. The brand pack's `graphic-language.md` outranks anything here.

## Which visual for which job

- **One number or a before and after** is a stat card. Most "can you make a graphic of this
  number" asks are this, not a chart.
- **Several series over time** is one line chart with one highlighted series, not five colours.
  Past three categories, colour stops encoding identity and starts encoding noise.
- **A dense matrix** (model by task, day by hour) reads as a heatmap; let the cell values carry
  the precision and the colour carry the pattern.
- **Quantities splitting and merging** (requests to outcomes) read cleaner as a sankey than as a
  node graph.
- **A trade-off between two measures** is a scatter with the one point that matters highlighted.
  If it spans orders of magnitude, transform the data first (or say a log axis is needed) rather than
  letting one point flatten the rest.
- **A loop** (a flywheel, a review cycle) is a cycle, not a left-to-right flow with a long return
  arrow. **A process with one loop back** is a diagram with a `feedback` edge.
- One idea per visual. Two stories are two renders.

## Words on the figure

- Sentence case on every label; never all caps unless the brand lists the term.
- A box is its label: no sub-line under a node, no legend or footer explaining the figure unless
  the ask supplied it or the figure misreads without it. Label an edge only when the arrow alone is
  ambiguous.
- Label lines and bars directly; a legend makes the reader match colours.
- Monospace only for code, file names and data columns, never as decoration.
- Numbers are figures with units, formatted by the renderer from the dataset (`34 min`, `$1,200`,
  `72%`), never typed into labels by hand.

## Size and legibility

- Legibility is type size divided by figure size. Narrowing the canvas enlarges the type as much as
  raising the font does; when labels crowd, try a narrower canvas before smaller type.
- Check at the size it is read: a blog figure at about 720 px wide, a slide at full screen, a social
  card on a phone.
- Type set larger than looks right at full resolution usually reads right once scaled into its page.

## Colour

- One accent element per frame: it is where the eye goes first.
- Light mid-tones rarely pass as text on a light ground. Carry a state (pass, fail, in progress) in
  the fill or the line style and keep the text in ink.
- A colour-encoded figure without printed values needs a key; with printed values it does not.

## Layout

- Balance the ink, not the boxes: a diagram that is wide and short sits in the middle of its frame;
  if the empty bands look wrong, change the canvas ratio (`width`, `height`) rather than padding.
- An axis with round steps (1, 2, 5, 10 multiples) prints exactly; the renderer picks them.
- After deleting a title, the content moves up and the canvas shrinks by the same amount, or the
  empty band reads as a mistake.

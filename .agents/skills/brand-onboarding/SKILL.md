---
name: brand-onboarding
description: Build the active brand pack in workspace/brand/ from a brand guide, website, files or a Paper file, validate it, and have a person review it.
---

# Build a brand pack

The pack is the agent's only source of brand facts: tokens, logos, fonts, voice and graphic
language. Schema: `src/design_agent/brand/schema.py`; a complete example:
`examples/brands/example-studio/`. Never invent a rule, colour, font or logo the sources do not show:
leave it out and list it as a question for the person.

1. `uv run design-agent brand init` copies the example pack into `workspace/brand/` (Git-ignored);
   replace every file's content, logos included.
2. **Sources, best first:** the brand's own guide (PDF), its design files (Paper: read tokens,
   palette and type nodes with `get_tokens`, `get_computed_styles`, `get_jsx`; never write to the
   brand file), the live website's CSS, then existing marketing files.
3. `tokens.json`: palette, font stacks for display, text and mono, radii, stroke, spacing, and the
   copy rules the guide states. Check every text/ground pair you list for WCAG contrast; mark
   accents that fail on light grounds as non-text. Say which colour plays which role in
   `design.roles.light` and `design.roles.dark` (`ground`, `ink`, `accent`, `muted`, `quiet`,
   `rule`, `series`, each a token): charts and diagrams use them, and otherwise guess from the
   palette. Porting an existing tokens file: names must be `--brand-*`, hexes carry `#`, `version`
   is `"1"`, unknown keys are refused, and every font stack ends in a generic family.
4. `logos/`: SVG where the brand provides it; every variant the guide allows (mark, lockup,
   reversed). Do not redraw or trace a logo; ask for files.
5. `fonts.toml`: for each face, an open font in `fonts/` or a licensed file the person supplies in
   `private-fonts/` (Git-ignored; it reaches the sandbox as deployment files or a mount). Never
   commit licensed fonts. `family` is the name inside the file (the sandbox resolves fonts by it),
   `weight` a CSS weight (`"400"`, or `"100 900"` for a variable face), `sha256` from
   `shasum -a 256 <file>`. `uv run design-agent fonts verify` checks all three. Web formats
   (`.woff2`, `.woff`) are fine: `tokens.css` declares them with `@font-face`. If a licensed face
   is unavailable, name the closest open fallback and say so in `graphic-language.md`.
6. `voice.md` and `graphic-language.md`: short, concrete, sourced ("headlines in sentence case",
   "one accent per frame"), no generic advice. Anything else the guide has (type tables, icons,
   pattern art, construction specs) can live in the pack too; link it from `graphic-language.md`,
   which is what the agent reads first.
7. `uv run design-agent brand validate`, `uv run design-agent fonts verify`, then
   `uv run design-agent brand css` regenerates `tokens.css`. For a first look, ask for one card
   (`uv run design-agent ask "A 1200x630 card announcing …"`) and review it with the person; `demo`
   always renders the sample brand.
8. Hand the person the open questions, including rules the guide contradicts itself on; the pack is
   done when they have reviewed it.
9. Tell them to redeploy. On Managed Deep Agents the pack ships with the deployment, so Slack keeps
   the old brand until `uv run mda deploy`; local runs pick it up at once.
10. Offer a Slack app icon in the new brand:
    `uv run design-agent ask "Our Slack app icon: a 1024x1024 PNG, the logo mark centred on the brand ground, no text"`.
    The person uploads it in the Slack app's settings (Basic Information, Display Information).
    Slack has no API for an app's icon, so neither MDA nor this repo can set it for them.

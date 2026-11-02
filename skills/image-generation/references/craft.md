# Prompt craft

A checklist for writing image prompts. Model capabilities move quickly; when a provider publishes a
prompting guide for the model in use, its advice wins (OpenAI's is in the public openai-cookbook
repository, "image-gen-models-prompting-guide").

## 1. Structure before subject

State the canvas, ratio and layout before describing the subject, or the model spends its detail on
the object and improvises the layout: "Landscape 16:9 editorial illustration, subject in the left
third, the right half calm and empty for type", "A 3×2 grid of six panels", "Square sticker, centred,
generous margin".

## 2. Leave room for the real type

Most generated images in this agent carry copy set later in HTML. Reserve the space explicitly
("a calm, empty band across the top 30% of the frame") and keep the focal subject out of it.

## 3. Words and marks

Default to "no text, no letters, no numbers, no logos, no watermark". If an image must contain
readable words (a sign in a scene that the brief requires), put the exact string in quotes, say it
must be crisp and legible, and expect to verify it letter by letter. Exact copy, the logo and anything
a person will read closely still belong in HTML.

## 4. Scene density beats adjectives

"A studio at night" is vague. Name five to twelve concrete things (a desk lamp's pool of light,
cable ties, a whiteboard with diagrams, a half-drunk coffee, rain on the window) and two to four
material and light constraints. Words like "stunning", "beautiful", "high quality" carry nothing.

## 5. Capture context for photorealism

Say how the picture was taken, not that it is realistic: "eye level, 35 mm lens feel, natural window
light from the left", "shot from across the room on a phone, slight motion blur". Pick one capture
frame; stacked camera specs conflict.

## 6. Material, light and palette are separate controls

Do not compress them into "premium". Materials (brushed steel, linen, frosted glass, paper grain),
light (softbox from above, low warm rim light, overcast daylight), palette (in words and the brand's
hex values). Separately controlled, each can be changed without disturbing the others.

## 7. Specific, bounded style anchors

Name a medium, technique or period rather than a mood: "19th-century steel engraving, fine
cross-hatching, monochrome", "risograph print, two inks, visible grain", "cut-paper collage with soft
drop shadows". Do not prompt in the style of a living artist or a studio's characters; keep subjects
and characters original.

## 8. Structured prompts for complex scenes

When many systems interact (environment, subject, materials, lighting, particles, motion), a
config-style prompt is easier to control and to vary than prose:

```text
{
  "canvas": "2:3 vertical, hero product centred, lower third empty",
  "style": "commercial studio photography, sharp foreground, micro texture",
  "environment": { "ground": "soft gradient in the brand's paper tone", "light": "large softbox above, gentle rim light" },
  "subject": { "object": "ceramic mug", "materials": ["matte glaze", "visible clay speckle"] },
  "detail": ["steam rising in a thin curl", "a few coffee beans in soft focus"],
  "avoid": ["text", "logos", "plastic CGI look"]
}
```

Keys describe visual subsystems; values are concrete constraints, not praise. Keep it readable.

## 9. Multi-panel coherence

For grids, storyboards and character sheets, state the panel count exactly, give each panel its beat,
and repeat the shared constraints (palette, light, the character's identifying features, camera
language) so panels belong to one world. For storyboard look plates, name the shot: wide, over the
shoulder, close-up, low angle.

## 10. Negation for strong priors only

Use a short, targeted avoid line where the model has a likely bad default ("avoid neon sci-fi,
avoid glossy 3D plastic, avoid fake interface text"). A long list of negatives dominates the prompt.

## 11. Three glances for hero images

First glance: the silhouette or theme is recognisable. Second: the idea or promise reads. Third:
close inspection rewards with texture and detail. Use it for posters, campaign heroes and thumbnails.

## 12. Iterating

- Change one control at a time between variants so you learn what moved the result.
- If every variant fails the same way, the prompt is the problem; rewrite it rather than re-rolling.
- Name exact counts ("exactly four characters", "three objects only") and an explicit projection or
  angle ("same isometric angle for every element") when the model keeps improvising them.
- Requests involving a real person's likeness usually fail at the provider's moderation layer;
  report its message as it is.

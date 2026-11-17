// Measure painted text runs at the sought time. A connector crossing a card or a
// repeated word in two columns is valid; two letters occupying the same space are not.
function checkLabels(scene) {
  const bounds = scene.getBoundingClientRect();
  const findings = new Set();
  const ids = new Set();
  for (const el of scene.querySelectorAll("[id]")) {
    if (ids.has(el.id)) findings.add("Duplicate element ID: " + el.id.slice(0, 60));
    ids.add(el.id);
  }
  function covered(el, box, fraction) {
    const x = box.left + box.width * fraction, y = box.top + box.height * 0.5;
    for (const layer of document.elementsFromPoint(x, y)) {
      if (el.contains(layer) || layer.contains(el)) return false;
      if (layer.tagName.toLowerCase() !== "rect" || !scene.contains(layer)) continue;
      const style = getComputedStyle(layer);
      if (style.fill === "none" || style.fill === "transparent" || Number(style.fillOpacity) < 0.95) continue;
      let opacity = 1;
      for (let p = layer; p && p !== scene; p = p.parentElement)
        opacity *= Number(getComputedStyle(p).opacity);
      if (opacity >= 0.95) return true;
    }
    return false;
  }
  const runs = [];
  const walker = document.createTreeWalker(scene, NodeFilter.SHOW_TEXT);
  for (let text; (text = walker.nextNode()); ) {
    const el = text.parentElement;
    const name = text.textContent.trim().slice(0, 48);
    if (!name || el.closest("style,script,defs,mask,clipPath,title,desc")) continue;
    if (!el.checkVisibility({opacityProperty: true, visibilityProperty: true})) continue;
    let opacity = 1;
    for (let parent = el; parent && parent !== scene; parent = parent.parentElement)
      opacity *= Number(getComputedStyle(parent).opacity);
    if (opacity < 0.35) continue;
    const range = document.createRange();
    range.selectNodeContents(text);
    for (const box of range.getClientRects()) {
      if (box.width < 2 || box.height < 2) continue;
      if (box.left < bounds.left - 2 || box.right > bounds.right + 2 ||
          box.top < bounds.top - 2 || box.bottom > bounds.bottom + 2)
        findings.add('Label outside canvas: "' + name + '"');
      if ([0.25, 0.5, 0.75].every(f => covered(el, box, f)))
        findings.add('Label covered by a panel: "' + name + '"');
      for (const run of runs) {
        const dx = Math.min(box.right, run.box.right) - Math.max(box.left, run.box.left);
        const dy = Math.min(box.bottom, run.box.bottom) - Math.max(box.top, run.box.top);
        if (dx > Math.max(2, Math.min(box.width, run.box.width) * 0.10) &&
            dy > Math.min(box.height, run.box.height) * 0.4)
          findings.add('Overlapping labels: "' + run.name + '" and "' + name + '"');
      }
      runs.push({name, box});
    }
  }
  return [...findings].slice(0, 12);
}

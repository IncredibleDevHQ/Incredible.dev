// SVG.js owns the artwork. GSAP owns every change on the narration's seekable clock.
const drawing = SVG(stage);
stage.setAttribute("data-illustration", "");
const margin = Math.min(width, height) * 0.055;
const fontSize = Math.max(18, Math.min(38, height * 0.034));
const gap = fontSize * 1.1;

// Choose a whole readable rectangle beside the presenter, whichever corner they occupy.
const full = {x: margin, y: margin, width: width - margin * 2, height: height - margin * 2};
let area = full;
if (brief.keep_clear) {
  const c = brief.keep_clear;
  const choices = [
    {...full, width: c.left - margin * 2},
    {...full, x: c.left + c.width + margin, width: width - c.left - c.width - margin * 2},
    {...full, height: c.top - margin * 2},
    {...full, y: c.top + c.height + margin, height: height - c.top - c.height - margin * 2},
  ].filter(r => r.width > fontSize * 7 && r.height > fontSize * 6);
  area = choices.sort((a,b) => b.width * b.height - a.width * a.height)[0];
  if (!area) throw new Error("The presenter leaves no readable illustration area. Use a content-only layout.");
}
stage.setAttribute("data-readable-area", JSON.stringify(area));

const relationships = brief.connections || [];
const edgeObjects = new Set(relationships.filter(e=>e.object!==e.from && e.object!==e.to).map(e=>e.object));
const registry = new Map();
for (const item of items)
  if (!item.from && !item.to && !edgeObjects.has(item.id) && !registry.has(item.id)) registry.set(item.id,item);
const connectorLayer = drawing.group();
const connectors = relationships.map((edge,i)=>({
  edge, path:connectorLayer.path("").fill("none").stroke({color:colors.accent,width:3,linecap:"round"}).attr({"data-connection":i,opacity:0}),
}));
const groups = new Map();
const measure = drawing.text("").font({family: brief.look.fonts.text, size: fontSize}).opacity(0);
function wrap(text, maxWidth) {
  const lines = [];
  let current = "";
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    const candidate = current ? current + " " + word : word;
    measure.text(candidate);
    if (measure.length() <= maxWidth) { current = candidate; continue; }
    if (current) lines.push(current);
    current = word;
    measure.text(current);
    while (measure.length() > maxWidth && current.length > 1) {
      let cut = current.length - 1;
      while (cut > 1 && measure.text(current.slice(0, cut)).length() > maxWidth) cut--;
      lines.push(current.slice(0, cut));
      current = current.slice(cut);
      measure.text(current);
    }
  }
  if (current) lines.push(current);
  return lines;
}

function glyph(container, item) {
  const asset = item.asset;
  const g = container.group().attr({"data-asset": asset});
  const pen = {color: colors.ink, width: 3, linecap: "round", linejoin: "round"};
  const line = d => g.path(d).fill("none").stroke(pen);
  if (asset === "phone") {
    g.rect(66, 108).move(31, 10).radius(12).fill(colors.panel).stroke(pen);
    g.rect(52, 78).move(38, 24).radius(5).fill(colors.ground);
    line("M39 72 L54 44 L75 61 L89 40 M40 90 L61 73 L88 86");
    g.path("M64 44 C45 44 45 68 64 83 C83 68 83 44 64 44Z").fill(colors.accent);
    g.circle(9).center(64, 58).fill(colors.panel);
    line("M57 17 H71 M58 110 H70");
  } else if (asset === "satellite") {
    g.rect(28, 38).center(64, 63).radius(6).fill(colors.panel).stroke(pen);
    for (const x of [8, 88]) {
      g.rect(32, 44).move(x, 42).fill(colors.accent).stroke(pen);
      line(`M${x+16} 43 V85 M${x+1} 56 H${x+31} M${x+1} 71 H${x+31}`);
    }
    line("M40 63 H50 M78 63 H88 M64 44 V28 M53 22 Q64 38 75 22 M64 83 V99 M53 106 Q64 92 75 106");
    g.circle(7).center(64, 64).fill(colors.accent);
  } else if (asset === "cloud") {
    g.path("M28 92 C1 92 1 54 27 52 C24 19 75 8 88 43 C122 32 137 85 105 92Z")
      .fill(colors.panel).stroke(pen);
    line("M43 75 H84 M52 64 H75");
  } else if (asset === "pin") {
    g.path("M64 12 C6 12 9 71 64 119 C119 71 122 12 64 12Z")
      .fill(colors.panel).stroke(pen);
    g.circle(31).center(64, 48).fill(colors.accent);
  } else if (asset === "object") {
    g.rect(80, 68).move(24, 32).radius(12).fill(colors.panel).stroke(pen);
    g.rect(30, 28).move(36, 46).radius(6).fill(colors.accent);
    line("M76 52 H93 M76 65 H89 M36 84 H93");
  } else {
    // Reuse the same participant silhouettes as flow and sequence diagrams.
    const holder = g.group().attr({transform:"translate(64 64)"});
    participant(0, 0, 1, asset, asset, holder.node);
  }
  return g;
}

for (const [id, item] of registry) {
  const group = drawing.group().attr({id:comp+"-asset-"+groups.size,"data-illustration-item":id,opacity:0});
  const art = group.nested().viewbox(0,0,128,128).attr({overflow:"hidden"});
  glyph(art, item);
  const caption = group.group().attr({"data-caption":""});
  groups.set(id, {item,group,art,caption});
}

function boxes(count, focused) {
  if (focused && count > 1 && area.width >= area.height * 1.2) {
    const heroWidth = area.width * 0.6 - gap / 2, sideWidth = area.width - heroWidth - gap;
    return [
      {x:area.x,y:area.y,width:heroWidth,height:area.height},
      ...Array.from({length:count-1},(_,i)=>({x:area.x+heroWidth+gap,y:area.y+i*(area.height+gap)/(count-1),width:sideWidth,height:(area.height-gap*(count-2))/(count-1)})),
    ];
  }
  const columns = Math.max(1, Math.min(count, Math.floor(area.width / (fontSize * 10))));
  const rows = Math.ceil(count / columns);
  const cw = (area.width-gap*(columns-1))/columns, ch = (area.height-gap*(rows-1))/rows;
  return Array.from({length:count},(_,i)=>({x:area.x+(i%columns)*(cw+gap),y:area.y+Math.floor(i/columns)*(ch+gap),width:cw,height:ch}));
}
const maxColumns = Math.max(1, Math.min(6, Math.floor(area.width / (fontSize * 10))));
const captionWidth = (area.width-gap*(maxColumns-1))/maxColumns-gap;
const captionLines = (item, width) => wrap(words(item), Math.min(width,captionWidth));
function fits(ids, focused) {
  const slots = boxes(ids.length,focused);
  return slots.every((box,i)=>box.width >= fontSize * 5 &&
    box.height >= captionLines(registry.get(ids[i]),box.width-gap).length*fontSize*1.25+fontSize*4+gap);
}
let lastVisible = new Set();
let currentPositions = new Map();
const introduced = new Set();
function compose(candidates, focal, focused, time, moveCamera) {
  const ordered = focused ? [focal, ...candidates] : candidates;
  const ids = [...new Set(ordered)].filter(id => registry.has(id));
  // Readability wins over fitting every supporting object into a tiny cell.
  let count = Math.min(focused ? 3 : 6, ids.length);
  while (count > 1 && !fits(ids.slice(0,count),focused)) count--;
  const selected = ids.slice(0,count);
  if (!selected.length) return;
  if (!fits(selected,focused)) throw new Error("Illustration caption needs a shorter label or a larger content area.");
  const slots = boxes(count, focused);
  const visible = new Set(selected.filter(id => introduced.has(id)));
  for (const {edge,path} of connectors) {
    if (!visible.has(edge.from) || !visible.has(edge.to)) {
      tl.set(path.node,{opacity:0},time);
      continue;
    }
    const a = slots[selected.indexOf(edge.from)], b = slots[selected.indexOf(edge.to)];
    const horizontal = Math.abs(a.x-b.x)>Math.abs(a.y-b.y);
    const direction = horizontal ? Math.sign(b.x-a.x) : Math.sign(b.y-a.y);
    const x1 = a.x+a.width/2+(horizontal?direction*a.width*0.36:0);
    const y1 = a.y+a.height*0.35+(horizontal?0:direction*a.height*0.26);
    const x2 = b.x+b.width/2-(horizontal?direction*b.width*0.36:0);
    const y2 = b.y+b.height*0.35-(horizontal?0:direction*b.height*0.26);
    const head = fontSize*0.25;
    const d = horizontal
      ? `M${x1} ${y1} L${x2} ${y2} M${x2-direction*head} ${y2-head} L${x2} ${y2} L${x2-direction*head} ${y2+head}`
      : `M${x1} ${y1} L${x2} ${y2} M${x2-head} ${y2-direction*head} L${x2} ${y2} L${x2+head} ${y2-direction*head}`;
    tl.set(path.node,{attr:{d}},time);
    const start = clock.cues[edge.cue] ?? clock.lines[edge.frame]?.[0] ?? time;
    tl.set(path.node,{opacity:time>start?1:0},time);
    if (time === start) {
      tl.fromTo(path.node, {opacity:0}, {opacity:1, duration:0.3, immediateRender:false}, start);
    }
  }
  for (const [id, value] of groups) {
    if (!visible.has(id)) {
      tl.set(value.group.node,{opacity:0},time);
      continue;
    }
    const box = slots[selected.indexOf(id)];
    const lines = captionLines(value.item,box.width-gap);
    const labelHeight = lines.length*fontSize*1.25;
    const artHeight = box.height-labelHeight-gap;
    // Asset zoom is constrained to its own slot, keeping labels and neighbours clear.
    const artSize = Math.min(box.width-gap,artHeight) * (focused && id===focal ? 0.96 : 0.82);
    const x = box.x+(box.width-artSize)/2, y = box.y+(artHeight-artSize)/2;
    // Labels are rebuilt only when their wrapping changes, never during a tween.
    const key = lines.join("\n");
    if (value.caption.attr("data-lines") !== key) {
      value.caption.clear().attr("data-lines",key);
      lines.forEach((text,i)=>{
        value.caption.text(text).font({family:brief.look.fonts.text,size:fontSize,weight:600})
          .fill(colors.ink).attr({"text-anchor":"middle","dominant-baseline":"middle",x:0,y:i*fontSize*1.25});
      });
    }
    const placement = JSON.stringify([x,y,artSize,box.x+box.width/2,box.y+artHeight+gap/2]);
    const changed = currentPositions.get(id)!==placement;
    if (moveCamera && changed) {
      const duration = Math.min(0.55, Math.max(0.08, (clock.seconds-time)*0.3));
      const sizeBefore = artSize * (focused && id === focal ? 0.74 : 1.12);
      const start = {
        x: x + (artSize-sizeBefore)/2,
        y: y + (artSize-sizeBefore)/2,
        width: sizeBefore,
        height: sizeBefore,
      };
      tl.fromTo(value.art.node, {attr:start}, {
        attr:{x,y,width:artSize,height:artSize}, duration, ease:"power2.inOut", immediateRender:false,
      }, time);
    } else if (changed || !lastVisible.has(id)) {
      tl.set(value.art.node, {attr:{x,y,width:artSize,height:artSize}}, time);
    }
    tl.set(value.caption.node,{attr:{transform:`translate(${box.x+box.width/2} ${box.y+artHeight+gap/2})`}},time);
    if (!lastVisible.has(id))
      tl.fromTo(value.group.node,{opacity:0},{opacity:1,duration:Math.min(0.32,Math.max(0.06,(clock.seconds-time)*0.3)),ease:"power1.out"},time);
    currentPositions.set(id,placement);
  }
  lastVisible=visible;
}

let known = [];
for (const line of brief.lines) {
  known = [...new Set([...known,...line.objects.map(o=>o.id)])];
  const cued = new Set(line.cues.map(c=>c.object));
  for (const obj of line.objects) if (!cued.has(obj.id)) introduced.add(obj.id);
  const focused = line.camera==="focus" || (variant==="focused" && line.camera!=="reset");
  const requests = line.visible?.length ? line.visible : [...line.objects.map(o=>o.id),...known];
  const focus = line.focal || requests[0];
  if (!introduced.size && registry.has(focus)) introduced.add(focus);
  const start = clock.lines[line.frame]?.[0] ?? 0;
  compose(requests,focus,focused,start,line.camera==="focus" || line.camera==="reset");
  for (const cue of [...line.cues].sort((a,b)=>(clock.cues[a.key]??start)-(clock.cues[b.key]??start))) {
    const time = clock.cues[cue.key] ?? start;
    const target = registry.has(cue.object) ? cue.object : null;
    if (target) introduced.add(target);
    const shot = target && !requests.includes(target) ? [target, ...requests] : requests;
    compose(shot, focused ? focus : target, focused, time, false);
    const value = groups.get(target);
    if (!value || cue.move==="hold") continue;
    if (cue.move==="emphasise" || cue.move==="count") {
      tl.fromTo(value.art.node,{opacity:0.45},{opacity:1,duration:0.45,ease:"power1.inOut",immediateRender:false},time);
    } else {
      const strokes = [...value.art.node.querySelectorAll("path[fill='none']")];
      for (const stroke of strokes) trace(stroke,time,Math.min(0.5,(clock.seconds-time)*0.4));
    }
  }
}
measure.remove();

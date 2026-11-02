/* motion-presets.js: frame presets and easing families for HyperFrames compositions.
 *
 * A film holds one easing family from start to finish, so every move feels made by one hand. A
 * family is a feel (durations, curves, offsets), never the film's metronome: how long a beat lasts
 * comes from what it asks the viewer to do (motion-direction, directing).
 *
 * Copy this file next to the composition (the sandbox has no network) and load it with a plain
 * script tag after the local copy of GSAP (media-production says where that copy lives). Then,
 * inside the composition's one paused timeline:
 *   var M = window.MotionPresets;
 *   var fam = M.family("silk");
 *   M.enter(tl, "#s2-headline", 0.4, fam);
 *   M.exit(tl, "#s2-headline", 3.1, fam);
 *
 * Everything here is a pure function of its arguments: no clock, no randomness (seeded() is a hash),
 * no timers. Tweens are added to the timeline you pass, never played on their own, so video-gate
 * passes. Animate children of a `.clip`, never the clip itself (hyperframes-core).
 */
(function (root) {
  "use strict";

  // Frame presets. Safe insets are fractions of the frame for the vertical cut, where feeds overlay
  // captions and buttons; check the platform's current template before a final (design-wiki).
  var ASPECTS = {
    landscape: { name: "16:9", width: 1920, height: 1080, fps: 30, use: "film master, slides, video players" },
    vertical: {
      name: "9:16", width: 1080, height: 1920, fps: 30, use: "shorts, reels, stories",
      safe: { top: 0.08, right: 0.12, bottom: 0.25, left: 0.06 }
    },
    square: { name: "1:1", width: 1080, height: 1080, fps: 30, use: "square feed posts" },
    portrait: { name: "4:5", width: 1080, height: 1350, fps: 30, use: "portrait feed posts" }
  };

  // Easing families. dur and exitDur are seconds; enter and exit are the offsets an element travels.
  // Exits are shorter than entrances, and ease in, so they accelerate out of the frame.
  var FAMILIES = {
    silk: {
      label: "Silk", feel: "smooth and continuous", use: "most beats, editorial, dashboards",
      dur: 0.45, ease: "power2.out", exitDur: 0.3, exitEase: "power2.in", stagger: 0.08,
      enter: { y: 18 }, exit: { y: -12 }
    },
    snap: {
      label: "Snap", feel: "instant and decisive", use: "code, commands, quick UI beats",
      dur: 0.18, ease: "power3.out", exitDur: 0.12, exitEase: "power2.in", stagger: 0.04,
      enter: { y: 8 }, exit: { y: 0 }
    },
    spring: {
      label: "Spring", feel: "lively, with one overshoot", use: "the payoff only, once or twice a film",
      dur: 0.5, ease: "back.out(1.4)", exitDur: 0.25, exitEase: "power2.in", stagger: 0.06,
      enter: { scale: 0.85 }, exit: { scale: 0.92 }
    },
    float: {
      label: "Float", feel: "weightless", use: "slow openings, calm hero frames",
      dur: 0.7, ease: "power4.out", exitDur: 0.45, exitEase: "power2.in", stagger: 0.1,
      enter: { y: 24 }, exit: { y: -16 }
    },
    pulse: {
      label: "Pulse", feel: "rhythmic", use: "a live status dot, a finite count of beats",
      dur: 0.6, ease: "sine.inOut", exitDur: 0.3, exitEase: "sine.in", stagger: 0,
      enter: { scale: 0.9 }, exit: { scale: 0.9 }
    }
  };

  // Words a brief uses, to the family that fits them.
  var VIBES = {
    smooth: "silk", calm: "silk", editorial: "silk", premium: "silk", elegant: "silk",
    fast: "snap", punchy: "snap", technical: "snap", decisive: "snap", code: "snap",
    playful: "spring", celebratory: "spring", bouncy: "spring",
    dreamy: "float", weightless: "float", cinematic: "float",
    rhythmic: "pulse", live: "pulse"
  };

  function family(name) {
    return FAMILIES[name] || FAMILIES.silk;
  }

  function pick(word) {
    return family(VIBES[String(word || "").toLowerCase()]);
  }

  function assign(target, source) {
    for (var key in source) if (Object.prototype.hasOwnProperty.call(source, key)) target[key] = source[key];
    return target;
  }

  function zeroed(offsets) {
    var out = {};
    for (var key in offsets) if (Object.prototype.hasOwnProperty.call(offsets, key)) out[key] = key === "scale" ? 1 : 0;
    return out;
  }

  // An entrance from the family's offset to rest, opacity included, added at `at` seconds.
  // opts: { dur, ease, stagger, from } override the family for this one move.
  function enter(timeline, targets, at, fam, opts) {
    var f = fam || FAMILIES.silk;
    var o = opts || {};
    var from = assign({ opacity: 0 }, o.from || f.enter);
    var to = assign(zeroed(o.from || f.enter), {
      opacity: 1,
      duration: o.dur != null ? o.dur : f.dur,
      ease: o.ease || f.ease,
      stagger: o.stagger != null ? o.stagger : f.stagger
    });
    return timeline.fromTo(targets, from, to, at);
  }

  // An exit to the family's offset, faster than the entrance, added at `at` seconds.
  function exit(timeline, targets, at, fam, opts) {
    var f = fam || FAMILIES.silk;
    var o = opts || {};
    var to = assign(assign({}, o.to || f.exit), {
      opacity: 0,
      duration: o.dur != null ? o.dur : f.exitDur,
      ease: o.ease || f.exitEase,
      stagger: o.stagger != null ? o.stagger : 0
    });
    return timeline.to(targets, to, at);
  }

  // A deterministic number in [0, 1) for a key: jitter, delays and spins that differ per element and
  // never between renders.
  function seeded(key) {
    var s = String(key);
    var h = 1779033703 ^ s.length;
    for (var i = 0; i < s.length; i++) {
      h = Math.imul(h ^ s.charCodeAt(i), 3432918353);
      h = (h << 13) | (h >>> 19);
    }
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    var a = ((h ^= h >>> 16) >>> 0) + 0x6d2b79f5;
    var t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  // A time snapped to its frame and backed off by half a millisecond, so an event never rounds past
  // the frame it belongs to.
  function onFrame(seconds, fps) {
    var rate = fps || 30;
    return Math.max(0, Math.round(seconds * rate) / rate - 0.0005);
  }

  // A zoom in log space: equal steps of progress read as equal steps of scale.
  function logZoom(from, to, progress) {
    var p = Math.min(1, Math.max(0, progress));
    return Math.exp(Math.log(from) + (Math.log(to) - Math.log(from)) * p);
  }

  // Overshoot of a damped spring as a fraction of its travel: exp(-zeta * pi / sqrt(1 - zeta^2)).
  function overshoot(zeta) {
    if (zeta >= 1) return 0;
    return Math.exp((-zeta * Math.PI) / Math.sqrt(1 - zeta * zeta));
  }

  var api = {
    ASPECTS: ASPECTS,
    FAMILIES: FAMILIES,
    VIBES: VIBES,
    family: family,
    pick: pick,
    enter: enter,
    exit: exit,
    seeded: seeded,
    onFrame: onFrame,
    logZoom: logZoom,
    overshoot: overshoot
  };
  root.MotionPresets = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : this);

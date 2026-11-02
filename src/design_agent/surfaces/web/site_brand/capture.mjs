// Reads the brand a website shows, inside a throwaway container of the sandbox image (its
// Chromium and Puppeteer): the one place a page from the internet runs. The page renders at
// 1920×1080 in light mode; one pass (page.js) collects how every colour is used, the faces the page
// sets text in and declares, its logo candidates, icons and the shape of its type and controls.
// The roles come from what each colour does (the studio's brand read, which matched HyperFrames'
// capture on 8 of 8 sites), and the files a brand pack needs are kept: the site's logo (safe SVG
// when it is drawn so, and a PNG of it alone), its best square icon, the font files of openly
// licensed faces (WOFF2 decompressed to TTF, named as the files name themselves), and the first
// screen. Requests to private, local or link-local addresses are refused.
//
// Usage: node capture.mjs <url> <out-dir>; writes <out-dir>/capture.json and the files it names.
import { execFile } from 'node:child_process'
import { promises as dns } from 'node:dns'
import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import net from 'node:net'
import path from 'node:path'
import { promisify } from 'node:util'

const require = createRequire('/opt/design-agent/render/')
const puppeteer = require('puppeteer-core')
const run = promisify(execFile)
const here = path.dirname(new URL(import.meta.url).pathname)
const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const warnings = []

// -- only the public internet ---------------------------------------------------------------

const privateV4 = (ip) => {
  const [a, b] = ip.split('.').map(Number)
  return (
    a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127) || a >= 224
  )
}
const privateIp = (ip) => {
  if (net.isIPv4(ip)) return privateV4(ip)
  const low = ip.toLowerCase()
  const mapped = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/.exec(low)
  if (mapped) return privateV4(mapped[1])
  return low === '::1' || low === '::' || /^f[cd]/.test(low) || /^fe[89ab]/.test(low) || /^ff/.test(low)
}
const checked = new Map()
const publicHost = async (raw) => {
  let url
  try {
    url = new URL(raw)
  } catch {
    return false
  }
  if (!/^https?:$/.test(url.protocol)) return false
  const host = url.hostname.replace(/^\[|\]$/g, '')
  if (!checked.has(host)) {
    checked.set(
      host,
      (net.isIP(host) ? Promise.resolve([{ address: host }]) : dns.lookup(host, { all: true }))
        .then((found) => found.length > 0 && found.every((entry) => !privateIp(entry.address)))
        .catch(() => false)
    )
  }
  return checked.get(host)
}
const fetchBytes = async (url, limit, accept = '*/*') => {
  if (!(await publicHost(url))) return null
  try {
    const response = await fetch(url, {
      headers: { 'user-agent': UA, accept },
      redirect: 'follow',
      signal: AbortSignal.timeout(10_000)
    })
    if (!response.ok || !(await publicHost(response.url))) return null
    const body = Buffer.from(await response.arrayBuffer())
    return body.length <= limit ? { body, type: response.headers.get('content-type') || '' } : null
  } catch {
    return null
  }
}

// -- colours by what they do (the studio's brand-colour.ts) -----------------------------------

const BROWSER_LINKS = new Set(['#0000EE', '#551A8B', '#0000FF', '#EE0000'])
const rgbOf = (hex) => [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16))
const lightness = (hex) => {
  const [r, g, b] = rgbOf(hex)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const colourfulness = (hex) => {
  const rgb = rgbOf(hex)
  return Math.max(...rgb) - Math.min(...rgb)
}
const valid = (hex) => /^#[0-9A-F]{6}$/i.test(hex)
const hueOf = (hex) => {
  const [r, g, b] = rgbOf(hex).map((value) => value / 255)
  const max = Math.max(r, g, b)
  const spread = max - Math.min(r, g, b)
  if (!spread) return 0
  const hue = max === r ? ((g - b) / spread) % 6 : max === g ? (b - r) / spread + 2 : (r - g) / spread + 4
  return (hue * 60 + 360) % 360
}
const hueDistance = (a, b) => {
  const distance = Math.abs(hueOf(a) - hueOf(b))
  return Math.min(distance, 360 - distance)
}
// The ground is what most of the first screen shows behind its content (page.js's votes); a page
// too broken up for a majority falls back to the studio's rule, the colour of the most large fills.
const brandRoles = (stats, palette, grounds = []) => {
  const usable = stats.map((stat) => ({ ...stat, hex: stat.hex.toUpperCase() })).filter((stat) => valid(stat.hex))
  if (!usable.length) return null
  const voted = grounds[0] && grounds[0].votes >= 9 ? grounds[0].hex.toUpperCase() : null
  const ground = voted || [...usable].sort((a, b) => b.areaBg - a.areaBg || b.maxArea - a.maxArea || b.bgCount - a.bgCount)[0].hex
  const order = new Map(palette.map((hex, at) => [hex.toUpperCase(), at]))
  const prominence = (hex) => order.get(hex) ?? 1e9
  const roles = (stat) => (stat.interactiveBg > 0 ? 1 : 0) + (stat.textCount > 0 ? 1 : 0) + (stat.bgCount > 0 ? 1 : 0)
  const colourful = palette.map((hex) => hex.toUpperCase()).filter((hex) => valid(hex) && colourfulness(hex) > 40)
  const weightOf = (hex) => 1 / (1 + prominence(hex) / 4)
  const total = colourful.reduce((sum, hex) => sum + weightOf(hex), 0) || 1
  const family = (hex) => colourful.filter((other) => hueDistance(other, hex) <= 18).reduce((sum, other) => sum + weightOf(other), 0) / total
  const seen = new Map(usable.map((stat) => [stat.hex, stat]))
  const blank = { count: 0, bgCount: 0, interactiveBg: 0, areaBg: 0, textCount: 0, maxArea: 0 }
  const pool = [...usable, ...colourful.filter((hex) => !seen.has(hex)).map((hex) => ({ ...blank, hex }))]
  const score = (stat) => {
    const rank = prominence(stat.hex)
    return 3 * roles(stat) + (stat.interactiveBg > 0 ? 2 : 0) + 4 * family(stat.hex) + (rank < 3 ? 1.5 : rank < 8 ? 1 : rank < 16 ? 0.5 : 0)
  }
  const accents = (exclude) =>
    pool
      .filter((stat) => colourfulness(stat.hex) > 40 && !exclude.includes(stat.hex) && !BROWSER_LINKS.has(stat.hex))
      .sort((a, b) => score(b) - score(a) || prominence(a.hex) - prominence(b.hex) || b.count - a.count || colourfulness(b.hex) - colourfulness(a.hex))
  const accent = accents([ground])[0]?.hex
  const groundLight = lightness(ground)
  const text =
    [...usable]
      .filter((stat) => stat.hex !== ground && stat.hex !== accent)
      .sort((a, b) => b.textCount - a.textCount)
      .find((stat) => Math.abs(lightness(stat.hex) - groundLight) > 64)?.hex ?? (groundLight > 128 ? '#111111' : '#F5F5F5')
  const colours = (accent ? accents([ground, text, accent]) : []).filter((stat) => {
    const [r, g, b] = rgbOf(stat.hex)
    const level = (Math.max(r, g, b) + Math.min(r, g, b)) / 510
    return level >= 0.12 && level <= 0.8
  })
  const second = (colours.find((stat) => hueDistance(stat.hex, accent) > 25) || colours[0])?.hex
  return { ground, text, ...(accent ? { accent } : {}), ...(second ? { second } : {}) }
}

// -- faces by name and role (the studio's brand-fonts.ts) ------------------------------------

const GENERIC = new Set(['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-serif', 'ui-sans-serif', 'ui-monospace', 'ui-rounded', '-apple-system', 'blinkmacsystemfont', 'segoe ui', 'emoji', 'math', 'fangsong', 'inherit', 'initial'])
const iconFont = (family) => /(?:^|[\s_-])icons?(?:[\s_-]|$)|icomoon|awesome|glyphicons?|material\s*(?:icons|symbols)|feather|(?:icon|glyph).*font|font.*(?:icon|glyph)/i.test(family)
const cleanFamily = (raw) => {
  let name = (raw || '').split(',')[0].replace(/["']/g, '').trim()
  name = name.replace(/\s+fallback(?:\s*:.*)?$/i, '')
  const nextFont = /^__(.+?)(?:_Fallback)?_[0-9a-f]{5,}$/i.exec(name)
  if (nextFont) name = nextFont[1].replace(/_/g, ' ')
  return name.replace(/[-_][0-9a-f]{6,}$/i, '').trim()
}
const OPEN = ['Albert Sans', 'Anton', 'Archivo', 'Atkinson Hyperlegible', 'Barlow', 'Be Vietnam Pro', 'Bebas Neue', 'Bitter', 'Bricolage Grotesque', 'Cabin', 'Commit Mono', 'Cormorant', 'Crimson Pro', 'DM Mono', 'DM Sans', 'DM Serif Display', 'EB Garamond', 'Epilogue', 'Figtree', 'Fira Code', 'Fira Mono', 'Fira Sans', 'Fraunces', 'Geist', 'Geist Mono', 'Hanken Grotesk', 'IBM Plex Mono', 'IBM Plex Sans', 'IBM Plex Serif', 'Inconsolata', 'Instrument Sans', 'Instrument Serif', 'Inter', 'Inter Display', 'Inter Tight', 'JetBrains Mono', 'Josefin Sans', 'Karla', 'Lato', 'Lexend', 'Libre Franklin', 'Literata', 'Lora', 'Manrope', 'Martian Mono', 'Merriweather', 'Montserrat', 'Mulish', 'Newsreader', 'Noto Sans', 'Noto Serif', 'Nunito', 'Nunito Sans', 'Onest', 'Open Sans', 'Oswald', 'Outfit', 'Overpass', 'Playfair Display', 'Plus Jakarta Sans', 'Poppins', 'PT Sans', 'PT Serif', 'Public Sans', 'Quicksand', 'Raleway', 'Recursive', 'Red Hat Display', 'Red Hat Mono', 'Red Hat Text', 'Roboto', 'Roboto Flex', 'Roboto Mono', 'Rubik', 'Schibsted Grotesk', 'Sora', 'Source Code Pro', 'Source Sans 3', 'Source Sans Pro', 'Source Serif 4', 'Source Serif Pro', 'Space Grotesk', 'Space Mono', 'Spectral', 'Ubuntu', 'Ubuntu Mono', 'Urbanist', 'Work Sans']
const keyOf = (family) => family.toLowerCase().replace(/[^a-z0-9]/g, '').replace(/(?:variable|var|vf)$/, '')
const OPEN_KEYS = new Map(OPEN.map((family) => [keyOf(family), family]))
for (const [alias, family] of [['geistsans', 'Geist'], ['geistmono', 'Geist Mono'], ['plexsans', 'IBM Plex Sans'], ['plexmono', 'IBM Plex Mono'], ['plexserif', 'IBM Plex Serif'], ['notioninter', 'Inter']]) OPEN_KEYS.set(alias, family)
const openFamily = (family) => OPEN_KEYS.get(keyOf(cleanFamily(family))) ?? null
const usableFamily = (family) => Boolean(family) && !GENERIC.has(family.trim().toLowerCase()) && !iconFont(family)
const fromVariables = (variables, pattern) => {
  for (const [name, value] of Object.entries(variables || {}))
    if (pattern.test(name)) {
      const family = cleanFamily(value)
      if (usableFamily(family)) return family
    }
  return ''
}
const named = (family) => openFamily(family) ?? family
const fontRoles = (signals) => {
  const ranked = signals.ranked.map((entry) => cleanFamily(entry.family)).filter(usableFamily)
  const mono = (family) => /mono|code|courier|menlo|consolas/i.test(family)
  const text = ranked.filter((family) => !mono(family))
  const pick = (...choices) => choices.map(cleanFamily).find(usableFamily) || ''
  const display = pick(signals.heading) || fromVariables(signals.variables, /display|heading|title/i) || text[0] || 'system-ui'
  const body = pick(signals.body) || fromVariables(signals.variables, /sans|body|text|base|copy/i) || text[1] || text[0] || display
  const code = [cleanFamily(signals.mono)].find((family) => usableFamily(family) && mono(family)) || fromVariables(signals.variables, /mono|code/i) || ranked.find(mono) || 'ui-monospace'
  return {
    display: named(mono(display) && text[0] ? text[0] : display),
    body: named(mono(body) && text[0] ? text[0] : body),
    mono: named(code),
    seen: [...new Set(ranked.map(named))].slice(0, 6)
  }
}

// -- font files of the open faces in use -----------------------------------------------------

const FORMATS = { wOF2: 'woff2', wOFF: 'woff', OTTO: 'otf', true: 'ttf', '\u0000\u0001\u0000\u0000': 'ttf' }
const fontFormat = (bytes) => FORMATS[bytes.subarray(0, 4).toString('latin1')] ?? null
const latinFirst = (face) => (!face.range || /U\+0+-0*FF\b|U\+0000-00FF/i.test(face.range) ? 0 : 1)
const facesIn = (css, base) =>
  [...css.matchAll(/@font-face\s*\{([^}]*)\}/gi)].map((match) => {
    const body = match[1]
    const value = (name) => new RegExp(`(?:^|;)\\s*${name}\\s*:\\s*([^;]+)`, 'i').exec(body)?.[1]?.trim() || ''
    const sources = [...value('src').matchAll(/url\(\s*(?:"([^"]+)"|'([^']+)'|([^)\s]+))\s*\)\s*(?:format\(\s*["']?([^"')]+)["']?\s*\))?/gi)]
      .map((source) => {
        try {
          return { url: new URL(source[1] || source[2] || source[3], base).href, format: source[4] || '' }
        } catch {
          return null
        }
      })
      .filter(Boolean)
    return { family: value('font-family').replace(/["']/g, ''), weight: value('font-weight') || '400', style: value('font-style') || 'normal', sources, range: value('unicode-range') }
  })

// What the file says it is: its own family name, weight and slant (fontconfig reads it).
const fontIdentity = async (file) => {
  try {
    const { stdout } = await run('fc-query', ['--format', '%{family[0]}|%{weight}|%{slant}\\n', file], { timeout: 10_000 })
    const [family, weight, slant] = stdout.trim().split('\n')[0].split('|')
    // fontconfig's weights: 40 light, 50 book, 80 regular, 100 medium, 180 semibold, 200 bold.
    const css = { 0: 100, 40: 200, 50: 300, 55: 350, 75: 400, 80: 400, 100: 500, 180: 600, 200: 700, 205: 800, 210: 900, 215: 950 }
    return { family, weight: css[Number(weight)] ?? 400, italic: Number(slant) > 0 }
  } catch {
    return null
  }
}

const keepFaces = async (read, roles, captured, outDir) => {
  const wanted = new Set([roles.display, roles.body, roles.mono].map(openFamily).filter(Boolean))
  if (!wanted.size) return []
  const faces = [...read.fonts.faces]
  for (const href of read.fonts.blocked.slice(0, 6)) {
    const sheet = await fetchBytes(href, 400 * 1024, 'text/css,*/*;q=0.5')
    if (sheet) faces.push(...facesIn(sheet.body.toString('utf8'), href))
  }
  faces.sort((a, b) => latinFirst(a) - latinFirst(b))
  const kept = []
  const seen = new Set()
  const stored = new Map()
  await fs.mkdir(path.join(outDir, 'fonts'), { recursive: true })
  for (const face of faces) {
    const family = openFamily(face.family)
    if (!family || !wanted.has(family) || kept.length >= 8) continue
    const style = /italic|oblique/i.test(face.style) ? 'italic' : 'normal'
    const key = `${family}|${face.weight}|${style}`
    if (seen.has(key)) continue
    const source = face.sources.find((entry) => /woff2/i.test(entry.format + entry.url)) || face.sources.find((entry) => !/eot|svg/i.test(entry.format + entry.url))
    if (!source) continue
    let file = stored.get(source.url)
    if (!file) {
      const body = captured.get(source.url) || (await fetchBytes(source.url, 2_000_000))?.body
      const format = body ? fontFormat(body) : null
      if (!body || !format) continue
      const base = path.join(outDir, 'fonts', `${keyOf(family)}-${stored.size}`)
      let target = `${base}.${format}`
      await fs.writeFile(target, body)
      if (format === 'woff2') {
        try {
          await run('woff2_decompress', [target], { timeout: 20_000 })
          await fs.rm(target)
          target = `${base}.ttf`
        } catch {
          warnings.push(`could not decompress ${family}`)
        }
      }
      const identity = /\.(ttf|otf)$/.test(target) ? await fontIdentity(target) : null
      file = { file: path.relative(outDir, target), format: path.extname(target).slice(1), identity }
      stored.set(source.url, file)
    }
    kept.push({ family, weight: face.weight, style, ...file })
    seen.add(key)
  }
  return kept
}

// -- the site's logo and icon (the studio's site-logo.ts, run inside the browser) --------------

const SANITIZE = `(markup) => {
  var ELEMENTS = new Set(['svg','g','path','rect','circle','ellipse','line','polyline','polygon','text','tspan','defs','symbol','use','title','desc','linearGradient','radialGradient','stop','clipPath','mask','pattern']);
  var ATTRIBUTES = new Set(['xmlns','xmlns:xlink','version','id','viewBox','preserveAspectRatio','width','height','x','y','x1','x2','y1','y2','cx','cy','r','rx','ry','fx','fy','d','points','transform','fill','fill-opacity','fill-rule','clip-rule','clip-path','mask','stroke','stroke-width','stroke-opacity','stroke-linecap','stroke-linejoin','stroke-miterlimit','stroke-dasharray','stroke-dashoffset','opacity','color','display','visibility','offset','stop-color','stop-opacity','gradientUnits','gradientTransform','patternUnits','patternTransform','maskUnits','clipPathUnits','spreadMethod','font-family','font-size','font-weight','font-style','letter-spacing','text-anchor','dominant-baseline','dx','dy','vector-effect','paint-order','href','xlink:href']);
  var OUTSIDE = /url\\(\\s*['"]?(?!#)|javascript:|expression\\s*\\(|@import/i;
  if (!/<svg[\\s>]/i.test(markup) || markup.length > 400000) return null;
  var found = /<svg[\\s\\S]*<\\/svg>/i.exec(markup);
  if (!found) return null;
  var root = new DOMParser().parseFromString(found[0], 'image/svg+xml').documentElement;
  if (!root || root.tagName !== 'svg') return null;
  var walk = function (element) {
    Array.from(element.children).forEach(function (child) {
      if (!ELEMENTS.has(child.tagName)) { child.remove(); return; }
      walk(child);
    });
    Array.from(element.attributes).forEach(function (attribute) {
      var name = attribute.name, value = attribute.value;
      var allowed = ATTRIBUTES.has(name) && !OUTSIDE.test(value) && ((name !== 'href' && name !== 'xlink:href') || value.charAt(0) === '#');
      if (!allowed) element.removeAttribute(name);
    });
  };
  walk(root);
  root.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  if (!root.querySelector('path, rect, circle, ellipse, polygon, text, use')) return null;
  return new XMLSerializer().serializeToString(root);
}`

const HEX = /#[0-9a-f]{6}\b|#[0-9a-f]{3}\b|rgba?\([^)]*\)/gi
const paintHex = (value) => {
  const short = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(value)
  if (short) return `#${short[1]}${short[1]}${short[2]}${short[2]}${short[3]}${short[3]}`.toUpperCase()
  if (/^#[0-9a-f]{6}$/i.test(value)) return value.toUpperCase()
  const rgb = /rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)(?:[\s,/]+([\d.]+))?/i.exec(value)
  if (!rgb || (rgb[4] !== undefined && Number(rgb[4]) === 0)) return null
  return `#${[rgb[1], rgb[2], rgb[3]].map((n) => Number(n).toString(16).padStart(2, '0')).join('')}`.toUpperCase()
}
const svgColours = (svg) => {
  const found = []
  for (const match of svg.matchAll(/(?:fill|stroke|stop-color|color)\s*=\s*"([^"]+)"/gi))
    for (const value of match[1].match(HEX) || []) {
      const hex = paintHex(value)
      if (hex && !found.includes(hex)) found.push(hex)
    }
  return found
}
// A one-colour drawing that would vanish on the ground takes the text colour.
const readableOn = (svg, ground, text) => {
  const colours = svgColours(svg)
  if (colours.length !== 1 || Math.abs(lightness(colours[0]) - lightness(ground)) > 64) return svg
  return svg.replace(/((?:fill|stroke|color)\s*=\s*")([^"]+)(")/gi, (whole, start, value, end) => (value.match(HEX) ? `${start}${text}${end}` : whole))
}
const largest = (sizes) =>
  Math.max(0, ...(sizes || '').split(/\s+/).map((token) => /^(\d+)x(\d+)$/i.exec(token)).filter(Boolean).map((match) => Math.max(Number(match[1]), Number(match[2]))))
const rankIcons = (icons) =>
  icons
    .filter((icon) => icon.href)
    .map((icon, at) => {
      const rel = icon.rel.toLowerCase()
      const file = icon.href.split(/[?#]/)[0].toLowerCase()
      const tier = /(^|\s)mask-icon(\s|$)/.test(rel) ? 3 : /svg/.test(icon.type || '') || file.endsWith('.svg') ? 0 : /icon/.test(icon.type || '') || file.endsWith('.ico') ? 2 : 1
      return { icon, at, tier, size: largest(icon.sizes) || (/apple-touch-icon/.test(rel) ? 180 : 0) }
    })
    .sort((a, b) => a.tier - b.tier || b.size - a.size || a.at - b.at)
    .map((entry) => entry.icon)

const sanitize = async (browser, markup) => {
  const page = await browser.newPage()
  try {
    return await page.evaluate(`(${SANITIZE})(${JSON.stringify(markup)})`)
  } catch {
    return null
  } finally {
    await page.close()
  }
}
const rasterize = async (browser, svg, height = 160) => {
  const page = await browser.newPage()
  try {
    await page.setViewport({ width: 1600, height: 400, deviceScaleFactor: 2 })
    await page.setContent(
      `<!doctype html><html><head><style>html,body{margin:0;background:transparent}img{display:block;height:${height}px;width:auto;max-width:1500px}</style></head><body><img id="l" src="data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}"></body></html>`,
      { waitUntil: 'load', timeout: 10_000 }
    )
    const image = await page.$('#l')
    const box = await image?.boundingBox()
    if (!image || !box || box.width < 4) return null
    return Buffer.from(await image.screenshot({ omitBackground: true }))
  } catch {
    return null
  } finally {
    await page.close()
  }
}
const isolate = async (page, index) => {
  const mark = `[data-brand-logo="${index}"]`
  const css = `html,body{background:transparent!important}body *:not(${mark}):not(${mark} *){visibility:hidden!important;background:transparent!important;box-shadow:none!important}${mark},${mark} *{visibility:visible!important}`
  try {
    await page.evaluate(`(() => { const style = document.createElement('style'); style.id = 'brand-isolate'; style.textContent = ${JSON.stringify(css)}; document.head.appendChild(style); })()`)
    const element = await page.$(mark)
    return element ? Buffer.from(await element.screenshot({ omitBackground: true })) : null
  } catch {
    return null
  } finally {
    await page.evaluate("document.getElementById('brand-isolate') && document.getElementById('brand-isolate').remove()").catch(() => undefined)
  }
}
// How much of a picture shows against a ground (a white logo on white shows none).
const visibleShare = async (browser, png, ground) => {
  const page = await browser.newPage()
  try {
    await page.setContent(`<img id="p" src="data:image/png;base64,${png.toString('base64')}">`, { waitUntil: 'load', timeout: 10_000 })
    const [r, g, b] = rgbOf(ground)
    return Number(
      await page.evaluate(
        `(() => { const img = document.getElementById('p'); if (!img.naturalWidth) return 0; const canvas = document.createElement('canvas'); canvas.width = img.naturalWidth; canvas.height = img.naturalHeight; const context = canvas.getContext('2d'); context.drawImage(img, 0, 0); const data = context.getImageData(0, 0, canvas.width, canvas.height).data; let shown = 0; for (let i = 0; i < data.length; i += 4) if (data[i + 3] > 40 && Math.abs(data[i] - ${r}) + Math.abs(data[i + 1] - ${g}) + Math.abs(data[i + 2] - ${b}) > 90) shown++; return shown / (data.length / 4); })()`
      )
    )
  } catch {
    return 0
  } finally {
    await page.close()
  }
}
const pngSize = (png) => (png.subarray(1, 4).toString('latin1') === 'PNG' ? { width: png.readUInt32BE(16), height: png.readUInt32BE(20) } : null)

const keepLogo = async (browser, page, read, roles, outDir) => {
  for (const candidate of read.logos) {
    let svg = candidate.markup ? await sanitize(browser, candidate.markup) : null
    if (!svg && candidate.src && /\.svg(\?|#|$)/i.test(candidate.src)) {
      const file = await fetchBytes(candidate.src, 400_000)
      const text = file?.body.toString('utf8') || ''
      if (text && !/<style|\sclass=/i.test(text)) svg = await sanitize(browser, text)
    }
    if (svg && roles) svg = readableOn(svg, roles.ground, roles.text)
    const png = svg ? await rasterize(browser, svg) : await isolate(page, candidate.index)
    if (!png || png.length < 200) continue
    if (roles && (await visibleShare(browser, png, roles.ground)) < 0.02) continue
    await fs.mkdir(path.join(outDir, 'logos'), { recursive: true })
    await fs.writeFile(path.join(outDir, 'logos', 'logo.png'), png)
    if (svg) await fs.writeFile(path.join(outDir, 'logos', 'logo.svg'), svg)
    return { png: 'logos/logo.png', ...(svg ? { svg: 'logos/logo.svg' } : {}), width: candidate.width, height: candidate.height, label: candidate.label }
  }
  return null
}
const keepSymbol = async (browser, read, outDir) => {
  for (const icon of rankIcons(read.icons).slice(0, 5)) {
    if (/\.ico(\?|$)/i.test(icon.href) || /mask-icon/i.test(icon.rel)) continue
    const file = await fetchBytes(icon.href, 600_000)
    if (!file) continue
    const svg = /svg/.test(file.type) ? await sanitize(browser, file.body.toString('utf8')) : null
    const png = svg ? await rasterize(browser, svg, 256) : /png/.test(file.type) ? file.body : null
    const size = png ? pngSize(png) : null
    if (!png || !size || Math.min(size.width, size.height) < 96) continue
    await fs.mkdir(path.join(outDir, 'logos'), { recursive: true })
    await fs.writeFile(path.join(outDir, 'logos', 'symbol.png'), png)
    if (svg) await fs.writeFile(path.join(outDir, 'logos', 'symbol.svg'), svg)
    return { png: 'logos/symbol.png', ...(svg ? { svg: 'logos/symbol.svg' } : {}), width: size.width, height: size.height }
  }
  return null
}

// -- the read ------------------------------------------------------------------------------

const main = async () => {
  const [url, outDir] = process.argv.slice(2)
  if (!url || !outDir) throw new Error('usage: node capture.mjs <url> <out-dir>')
  if (!(await publicHost(url))) throw new Error('That address is not on the public internet.')
  const pageScript = (await fs.readFile(path.join(here, 'page.js'), 'utf8')).replace(/^\/\/.*\n/gm, '')
  const browser = await puppeteer.launch({
    executablePath: '/usr/local/bin/chrome-headless-shell',
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--hide-scrollbars', '--font-render-hinting=none']
  })
  try {
    const page = await browser.newPage()
    await page.setBypassServiceWorker(true)
    const session = await page.createCDPSession()
    await session.send('Network.enable')
    await session.send('Network.setBlockedURLs', { urls: ['ws://*', 'wss://*'] })
    await page.setRequestInterception(true)
    page.on('request', (request) => {
      if (/^(data|blob):/.test(request.url())) return void request.continue().catch(() => {})
      void publicHost(request.url())
        .then((ok) => (ok ? request.continue() : request.abort()))
        .catch(() => {})
    })
    await page.setUserAgent(UA)
    await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 2 })
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'light' }])
    const captured = new Map()
    page.on('response', (response) => {
      if (response.request().resourceType() !== 'font' || captured.size >= 24) return
      if (Number(response.headers()['content-length']) > 2_000_000) return
      response
        .buffer()
        .then((body) => body.length <= 2_000_000 && captured.set(response.url(), body))
        .catch(() => undefined)
    })
    const loaded = await page.goto(url, { waitUntil: 'networkidle2', timeout: 30_000 }).catch((error) => {
      warnings.push(`the page kept loading: ${error.message.slice(0, 120)}`)
      return null
    })
    if (!loaded && page.url() === 'about:blank') throw new Error('The page did not load.')
    await wait(1000)
    // A protection page (a human check, a block) is never read as the brand (HyperFrames'
    // pageBlockDetection): the read stops and says so.
    const evidence = await page.evaluate(
      `(() => ({ title: document.title || '', text: (document.body && document.body.innerText || '').trim().length, children: document.body ? document.body.children.length : 0, challenge: Boolean(document.querySelector('#challenge-form, #challenge-stage, #cf-challenge-running, .cf-browser-verification, iframe[src*="challenges.cloudflare.com"], [id^="cf-chl"], [class*="turnstile"]')) || /verify you are human|performing security verification|checking your browser/i.test(document.body ? document.body.innerText : '') }))()`
    )
    const status = loaded ? loaded.status() : null
    const minimal = evidence.children <= 8 && evidence.text < 800
    const blockedTitle = /^(?:(?:error\s*)?(?:401|403|429)\b.*|forbidden|access denied|attention required!?|just a moment(?:\.{3})?)(?:\s*[|—-]\s*cloudflare)?$/i.test(evidence.title.trim())
    if (minimal && (evidence.challenge || blockedTitle || status === 401 || status === 403 || status === 429))
      throw new Error(`The site answered with a human check or a block (${status ? `HTTP ${status}` : 'no status'}, “${evidence.title}”), so it can't be read automatically. Try another page of the site, or bring its brand files.`)
    await page.evaluate('window.scrollTo(0, Math.min(document.body.scrollHeight, innerHeight * 4))').catch(() => undefined)
    await wait(600)
    await page.evaluate('window.scrollTo(0, 0)').catch(() => undefined)
    await page.evaluate('document.fonts ? document.fonts.ready.then(() => true) : true').catch(() => undefined)
    await wait(400)
    const read = await page.evaluate(pageScript)
    read.palette = (Array.isArray(read.palette) ? read.palette : []).filter((colour) => /^#[0-9a-f]{6}$/i.test(colour)).slice(0, 24)
    await page.screenshot({ path: path.join(outDir, 'first-screen.jpg'), type: 'jpeg', quality: 82 })
    const roles = brandRoles(read.stats, read.palette, read.grounds)
    const fonts = fontRoles(read.fonts)
    const fontFiles = await keepFaces(read, fonts, captured, outDir)
    const logo = await keepLogo(browser, page, read, roles, outDir)
    const symbol = await keepSymbol(browser, read, outDir)
    const result = {
      url,
      finalUrl: page.url(),
      host: new URL(page.url() || url).hostname.replace(/^www\./, ''),
      meta: read.meta,
      palette: read.palette,
      stats: read.stats.slice(0, 24),
      grounds: read.grounds,
      roles,
      fonts: { ...fonts, faces: read.fonts.faces.length, loaded: read.fonts.loaded.slice(0, 20) },
      fontFiles,
      logo,
      symbol,
      shape: read.shape,
      firstScreen: 'first-screen.jpg',
      warnings
    }
    await fs.writeFile(path.join(outDir, 'capture.json'), JSON.stringify(result, null, 2))
  } finally {
    await browser.close().catch(() => undefined)
  }
}

main().catch(async (error) => {
  console.error(error?.message || String(error))
  process.exit(1)
})

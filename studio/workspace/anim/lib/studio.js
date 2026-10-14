/* studio.js — charte d'animation des Shorts (scène SVG 1080×1920 déterministe).
 *
 *   <script src="lib/studio.js"></script>
 *   <script>
 *   const s = Studio.scene({theme: "night", accent: "#FFB938"});
 *   s.title("TAMBORA", {at: 0.1, sub: "la plus puissante éruption"});
 *   s.icon("volcano", {x: 540, y: 820, size: 560, at: 0.3, enter: "pop", idle: "float"});
 *   s.tag("INDONÉSIE", {x: 540, y: 1150, at: 0.9});
 *   </script>
 *
 * Tout est fonction de t (renderFrame est posé automatiquement) : aucune horloge réelle.
 * Options communes à tous les éléments : at (s), dur (durée d'entrée, 0.45), enter
 * (pop|fade|up|down|left|right|grow|draw|none), out (instant de sortie), exit (fade|pop|up|down),
 * idle (float|pulse|spin|wiggle), opacity, rotate (deg), scale, bleed (fond qui peut déborder : pas d'alerte de zone).
 * Zone utile : y 170-1200 (au-dessous : sous-titres puis interface TikTok), x 60-960 (icônes à droite).
 */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const W = 1080, H = 1920;
  const THEMES = {
    night: {bg: "#0B0B12", bg2: "#1A1626", ink: "#FFFFFF", muted: "#9A97A8", accent: "#FFB938", accent2: "#5EC8FF", glow: 0.28},
    space: {bg: "#05060F", bg2: "#14204A", ink: "#FFFFFF", muted: "#8E9BC4", accent: "#FFD15C", accent2: "#7CF0FF", glow: 0.22},
    paper: {bg: "#F3EAD9", bg2: "#E6D6B8", ink: "#1E1A16", muted: "#7A6E60", accent: "#E4572E", accent2: "#2E86AB", glow: 0.0},
    blueprint: {bg: "#0C2340", bg2: "#123A66", ink: "#EAF4FF", muted: "#8FB3D9", accent: "#FFD23F", accent2: "#FF6B6B", glow: 0.15},
    lab: {bg: "#0E1514", bg2: "#173A33", ink: "#F2FFFB", muted: "#8FB8AE", accent: "#3DF5A7", accent2: "#FF7AB6", glow: 0.25},
  };
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const E = {
    out: (x) => 1 - Math.pow(1 - clamp(x), 3),
    inOut: (x) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; },
    back: (x) => { x = clamp(x); const c = 1.70158, c3 = c + 1; return 1 + c3 * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); },
    elastic: (x) => { x = clamp(x); return x === 0 || x === 1 ? x : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * (2 * Math.PI) / 3) + 1; },
  };

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs || {}) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  // Image d'icône : une icône inconnue fait échouer le rendu avec un message clair (au lieu d'un vide).
  function iconImage(name, size, parent, extra) {
    const img = el("image", Object.assign({href: `lib/icons/${name}.svg`, x: -size / 2, y: -size / 2, width: size, height: size}, extra || {}), parent);
    img.addEventListener("error", () => { throw new Error(`icone inconnue : ${name} (liste : lib/icons/INDEX.txt)`); });
    return img;
  }

  function injectFonts() {
    if (document.getElementById("studio-fonts")) return;
    const st = document.createElement("style");
    st.id = "studio-fonts";
    st.textContent = `
      @font-face{font-family:"Studio";font-weight:900;src:url("lib/fonts/Poppins-Black.ttf")}
      @font-face{font-family:"Studio";font-weight:800;src:url("lib/fonts/Poppins-ExtraBold.ttf")}
      @font-face{font-family:"Studio";font-weight:600;src:url("lib/fonts/Poppins-SemiBold.ttf")}
      html,body{margin:0;width:${W}px;height:${H}px;overflow:hidden;background:#000}
      svg text{font-family:"Studio","DejaVu Sans",sans-serif}`;
    document.head.appendChild(st);
  }

  class Scene {
    constructor(opts = {}) {
      injectFonts();
      this.th = Object.assign({}, THEMES[opts.theme || "night"] || THEMES.night);
      if (opts.accent) this.th.accent = opts.accent;
      if (opts.accent2) this.th.accent2 = opts.accent2;
      this.items = [];
      this.cams = [];
      this.shakes = [];
      this.flashes = [];
      this.fitted = false;
      const svg = el("svg", {width: W, height: H, viewBox: `0 0 ${W} ${H}`});
      document.body.appendChild(svg);
      this.svg = svg;
      const defs = el("defs", {}, svg);
      this.defs = defs;
      const rg = el("radialGradient", {id: "bgGlow", cx: "50%", cy: "40%", r: "60%"}, defs);
      el("stop", {offset: "0%", "stop-color": this.th.bg2}, rg);
      el("stop", {offset: "100%", "stop-color": this.th.bg}, rg);
      const ag = el("radialGradient", {id: "accGlow", cx: "50%", cy: "50%", r: "50%"}, defs);
      el("stop", {offset: "0%", "stop-color": this.th.accent, "stop-opacity": this.th.glow}, ag);
      el("stop", {offset: "100%", "stop-color": this.th.accent, "stop-opacity": 0}, ag);
      const sh = el("filter", {id: "shadow", x: "-20%", y: "-20%", width: "140%", height: "140%"}, defs);
      el("feDropShadow", {dx: 0, dy: 10, stdDeviation: 14, "flood-color": "#000", "flood-opacity": opts.theme === "paper" ? 0.18 : 0.45}, sh);
      el("rect", {x: 0, y: 0, width: W, height: H, fill: "url(#bgGlow)"}, svg);
      if (opts.theme === "blueprint") {
        const grid = el("g", {stroke: this.th.muted, "stroke-opacity": 0.12, "stroke-width": 2}, svg);
        for (let x = 0; x <= W; x += 90) el("line", {x1: x, y1: 0, x2: x, y2: H}, grid);
        for (let y = 0; y <= H; y += 90) el("line", {x1: 0, y1: y, x2: W, y2: y}, grid);
      }
      this.glow = el("ellipse", {cx: 540, cy: opts.glowY || 760, rx: 620, ry: 620, fill: "url(#accGlow)"}, svg);
      this.world = el("g", {}, svg);      // couche soumise à la caméra
      this.overlay = el("g", {}, svg);    // titres (fixes)
      // Flash teinté de l'accent, en mode « screen » : éclaire sans délaver les noirs.
      this.flashRect = el("rect", {x: 0, y: 0, width: W, height: H, fill: this.th.accent, opacity: 0, style: "mix-blend-mode:screen"}, svg);
      // Vignettage léger pour la finition.
      const vg = el("radialGradient", {id: "vign", cx: "50%", cy: "45%", r: "75%"}, defs);
      el("stop", {offset: "60%", "stop-color": "#000", "stop-opacity": 0}, vg);
      el("stop", {offset: "100%", "stop-color": "#000", "stop-opacity": opts.theme === "paper" ? 0.18 : 0.55}, vg);
      el("rect", {x: 0, y: 0, width: W, height: H, fill: "url(#vign)", "pointer-events": "none"}, svg);
      window.renderFrame = (t) => this.render(t);
      window.__studioCheck = () => this.check();
    }

    // Contrôle des zones (appelé par le moteur de rendu après la dernière image) : contenu hors de
    // y 140-1200 (sous-titres puis interface TikTok en dessous) ou de x 40-970 (icônes TikTok à droite).
    check() {
      const out = [];
      const describe = (it) => {
        const txt = it.node.textContent ? it.node.textContent.trim().slice(0, 24) : "";
        const img = it.node.querySelector("image");
        return txt ? `« ${txt} »` : img ? (img.getAttribute("href") || "").replace("lib/icons/", "").replace(".svg", "") : "élément";
      };
      for (const it of this.items) {
        if (it.bleed || +it.node.getAttribute("opacity") < 0.05) continue;  // bleed : fond qui déborde exprès
        const r = it.node.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        const pb = [];
        if (r.bottom > 1205) pb.push(`descend à y ${Math.round(r.bottom)} (sous-titres dès 1220)`);
        if (r.right > 970) pb.push(`déborde à droite x ${Math.round(r.right)} (icônes TikTok après 960)`);
        if (r.left < 35) pb.push(`colle au bord gauche x ${Math.round(r.left)}`);
        if (r.top < 130) pb.push(`monte à y ${Math.round(r.top)}`);
        if (pb.length) out.push(`${describe(it)} ${pb.join(", ")}`);
      }
      // Taille : icônes isolées trop petites et scène globalement vide (vu sur téléphone, le petit disparaît).
      let covered = 0;
      const ux0 = 60, ux1 = 960, uy0 = 170, uy1 = 1180;
      for (const it of this.items) {
        if (it.layer === "overlay" || it.bleed || +it.node.getAttribute("opacity") < 0.05) continue;
        const r = it.node.getBoundingClientRect();
        const w = Math.max(0, Math.min(r.right, ux1) - Math.max(r.left, ux0));
        const h = Math.max(0, Math.min(r.bottom, uy1) - Math.max(r.top, uy0));
        covered += w * h;
        const imgs = it.node.querySelectorAll(":scope > image");
        if (imgs.length === 1 && r.width >= 1 && r.width < 170) out.push(`icône ${describe(it)} petite (${Math.round(r.width)} px, viser ≥ 250)`);
      }
      // Texte recouvert par une icône (ou l'inverse) : illisible.
      const vis = this.items.filter((it) => !it.bleed && +it.node.getAttribute("opacity") >= 0.05);
      const texts = vis.filter((it) => it.node.querySelector("text") && !it.node.querySelector("image"));
      const icons = vis.filter((it) => it.node.querySelector(":scope > image"));
      for (const a of texts) {
        const ra = a.node.getBoundingClientRect();
        const area = ra.width * ra.height;
        if (!area) continue;
        for (const b of icons) {
          const rb = b.node.getBoundingClientRect();
          const w = Math.max(0, Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left));
          const h = Math.max(0, Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top));
          if (w * h > 0.3 * area) out.push(`${describe(a)} chevauche l'icône ${describe(b)}`);
        }
      }
      const ratio = covered / ((ux1 - ux0) * (uy1 - uy0));
      if (this.items.length && ratio < 0.28) out.push(`scène vide : les éléments couvrent ~${Math.round(ratio * 100)} % de la zone utile (viser ≥ 35 % : agrandir ou zoom caméra)`);
      return out;
    }

    color(c) { return c === "accent" ? this.th.accent : c === "accent2" ? this.th.accent2 : c === "ink" ? this.th.ink : c === "muted" ? this.th.muted : (c || this.th.ink); }

    // ── mécanique commune ──
    _add(node, o, update) {
      const item = Object.assign({at: 0, dur: 0.35, enter: "pop", exit: "fade", exitDur: 0.3, x: 540, y: 960, scale: 1, rotate: 0, opacity: 1}, o, {node, update});
      (o.layer === "overlay" ? this.overlay : this.world).appendChild(node);
      this.items.push(item);
      return item;
    }

    _apply(it, t) {
      const k = (t - it.at) / it.dur;
      let op = it.opacity, sc = it.scale, dx = 0, dy = 0, rot = it.rotate;
      if (t < it.at) { it.node.setAttribute("opacity", 0); return -1; }
      const e = E.out(k), b = E.back(k);
      switch (it.enter) {
        case "pop": sc *= 0.55 + 0.45 * b; op *= clamp(k * 4); break;
        case "grow": sc *= E.out(k); break;
        case "fade": op *= e; break;
        case "up": dy = (1 - e) * 120; op *= e; break;
        case "down": dy = -(1 - e) * 120; op *= e; break;
        case "left": dx = (1 - e) * 220; op *= e; break;
        case "right": dx = -(1 - e) * 220; op *= e; break;
        case "drop": dy = -(1 - E.elastic(k)) * 500; op *= clamp(k * 4); break;
        default: break;
      }
      if (it.out !== undefined && t >= it.out) {
        const x = E.inOut((t - it.out) / it.exitDur);
        if (it.exit === "pop") sc *= 1 - x; else if (it.exit === "up") { dy -= 160 * x; op *= 1 - x; }
        else if (it.exit === "down") { dy += 160 * x; op *= 1 - x; } else op *= 1 - x;
      }
      const life = t - it.at;
      if (it.idle === "float") dy += Math.sin(life * 2.2) * 12;
      else if (it.idle === "pulse") sc *= 1 + 0.045 * Math.sin(life * 5);
      else if (it.idle === "spin") rot += life * 40;
      else if (it.idle === "wiggle") rot += Math.sin(life * 9) * 4;
      it.node.setAttribute("opacity", clamp(op));
      it.node.setAttribute("transform", `translate(${it.x + dx} ${it.y + dy}) rotate(${rot}) scale(${sc})`);
      return clamp(k);
    }

    // ── éléments ──
    title(text, o = {}) {
      const g = el("g", {});
      const size = o.size || 132;
      const t1 = el("text", {x: 0, y: 0, "text-anchor": "middle", "font-weight": 900, "font-size": size, fill: this.color(o.color || "ink"), filter: "url(#shadow)", "letter-spacing": 1}, g);
      t1.textContent = text;
      let sub = null;
      if (o.sub) {
        sub = el("text", {x: 0, y: size * 0.62, "text-anchor": "middle", "font-weight": 800, "font-size": o.subSize || 54, fill: this.color(o.subColor || "accent"), "letter-spacing": 2}, g);
        sub.textContent = o.sub.toUpperCase();
      }
      // Le mot-clé est là dès la coupe (la coupe fait le mouvement) : pas d'écran vide en début de plan.
      return this._add(g, Object.assign({x: 540, y: o.y || 330, enter: "none", layer: "overlay", fit: [t1, sub], maxW: 820}, o));
    }

    text(text, o = {}) {
      const g = el("g", {});
      const lines = String(text).split("\n");
      const size = o.size || 84;
      lines.forEach((ln, i) => {
        const n = el("text", {x: 0, y: i * size * 1.12, "text-anchor": o.anchor || "middle", "dominant-baseline": "middle", "font-weight": o.weight || 800, "font-size": size, fill: this.color(o.color || "ink")}, g);
        n.textContent = ln;
      });
      return this._add(g, Object.assign({fit: Array.from(g.childNodes), maxW: o.maxW || 820}, o));
    }

    tag(text, o = {}) {
      const g = el("g", {});
      const size = o.size || 44;
      const fg = this.color(o.color || "accent");
      const rect = el("rect", {rx: 10, fill: o.fill ? this.color(o.fill) : "none", stroke: fg, "stroke-width": 4}, g);
      const n = el("text", {x: 0, y: 0, "text-anchor": "middle", "dominant-baseline": "central", "font-weight": 800, "font-size": size, fill: o.fill ? this.th.bg : fg, "letter-spacing": 3}, g);
      n.textContent = text.toUpperCase();
      const item = this._add(g, Object.assign({enter: "up"}, o));
      item.boxed = {rect, n, pad: size * 0.45};
      return item;
    }

    icon(name, o = {}) {
      const g = el("g", {});
      const size = o.size || 400;
      iconImage(name, size, g, {filter: o.shadow === false ? "" : "url(#shadow)"});
      if (o.flip) g.firstChild.setAttribute("transform", "scale(-1 1)");
      return this._add(g, o);
    }

    circle(o = {}) {
      const g = el("g", {});
      el("circle", {cx: 0, cy: 0, r: o.r || 100, fill: this.color(o.fill || "none"), stroke: o.stroke ? this.color(o.stroke) : "none", "stroke-width": o.width || 8, "stroke-dasharray": o.dashed ? "18 14" : ""}, g);
      return this._add(g, o);
    }

    rect(o = {}) {
      const g = el("g", {});
      const w = o.w || 300, h = o.h || 200;
      el("rect", {x: -w / 2, y: -h / 2, width: w, height: h, rx: o.r || 24, fill: this.color(o.fill || "none"), stroke: o.stroke ? this.color(o.stroke) : "none", "stroke-width": o.width || 6}, g);
      return this._add(g, o);
    }

    counter(o = {}) {
      const g = el("g", {});
      const n = el("text", {x: 0, y: 0, "text-anchor": "middle", "dominant-baseline": "central", "font-weight": 900, "font-size": o.size || 180, fill: this.color(o.color || "accent"), filter: "url(#shadow)"}, g);
      if (o.label) {
        const l = el("text", {x: 0, y: (o.size || 180) * 0.75, "text-anchor": "middle", "font-weight": 800, "font-size": o.labelSize || 56, fill: this.color("ink")}, g);
        l.textContent = o.label;
      }
      const from = +o.from || 0, to = +o.to || 0, dec = o.decimals || 0, cd = o.countDur || 1.4;
      const fmt = (v) => (o.prefix || "") + v.toLocaleString("fr-FR", {minimumFractionDigits: dec, maximumFractionDigits: dec}) + (o.suffix || "");
      const it = this._add(g, Object.assign({fit: [n], maxW: 820}, o), (t, it) => {
        n.textContent = fmt(from + (to - from) * E.out((t - it.at) / cd));
      });
      n.textContent = fmt(to);
      return it;
    }

    arrow(o = {}) {
      const [x1, y1] = o.from || [200, 900], [x2, y2] = o.to || [880, 900];
      const bend = o.bend === undefined ? 0.25 : o.bend;
      const mx = (x1 + x2) / 2 - (y2 - y1) * bend, my = (y1 + y2) / 2 + (x2 - x1) * bend;
      const g = el("g", {});
      const col = this.color(o.color || "accent");
      const p = el("path", {d: `M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}`, fill: "none", stroke: col, "stroke-width": o.width || 12, "stroke-linecap": "round", "stroke-dasharray": o.dashed ? "4 26" : ""}, g);
      const head = el("path", {d: "M-34 -24 L0 0 L-34 24", fill: "none", stroke: col, "stroke-width": o.width || 12, "stroke-linecap": "round", "stroke-linejoin": "round"}, g);
      const len = p.getTotalLength();
      const it = this._add(g, Object.assign({x: 0, y: 0, enter: "none", dur: o.dur || 0.7}, o), (t, it) => {
        const k = E.inOut((t - it.at) / it.dur);
        if (!o.dashed) { p.setAttribute("stroke-dasharray", `${len} ${len}`); p.setAttribute("stroke-dashoffset", len * (1 - k)); }
        else p.setAttribute("stroke-dashoffset", -t * 60);
        const pt = p.getPointAtLength(Math.max(0.01, len * k)), pb = p.getPointAtLength(Math.max(0, len * k - 2));
        const ang = Math.atan2(pt.y - pb.y, pt.x - pb.x) * 180 / Math.PI;
        head.setAttribute("transform", `translate(${pt.x} ${pt.y}) rotate(${ang})`);
        head.setAttribute("opacity", k > 0.02 ? 1 : 0);
        if (o.dashed) p.setAttribute("opacity", 1);
      });
      return it;
    }

    // Objet qui suit un chemin (ex. avion, comète) : icon + path.
    travel(name, o = {}) {
      const [x1, y1] = o.from, [x2, y2] = o.to;
      const bend = o.bend === undefined ? 0.2 : o.bend;
      const mx = (x1 + x2) / 2 - (y2 - y1) * bend, my = (y1 + y2) / 2 + (x2 - x1) * bend;
      const path = el("path", {d: `M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}`});
      const len = (this.defs.appendChild(path), path.getTotalLength());
      const g = el("g", {});
      const size = o.size || 160;
      iconImage(name, size, g);
      const it = this._add(g, Object.assign({enter: "fade", dur: o.dur || 1.5}, o), (t, it) => {
        const k = E.inOut((t - it.at) / it.dur);
        const pt = path.getPointAtLength(len * k);
        it.x = pt.x; it.y = pt.y;
      });
      return it;
    }

    bar(o = {}) {
      const g = el("g", {});
      const w = o.w || 760, h = o.h || 56, col = this.color(o.color || "accent");
      el("rect", {x: -w / 2, y: -h / 2, width: w, height: h, rx: h / 2, fill: "none", stroke: this.th.muted, "stroke-width": 4}, g);
      const fill = el("rect", {x: -w / 2 + 8, y: -h / 2 + 8, width: 0, height: h - 16, rx: (h - 16) / 2, fill: col}, g);
      let lab = null;
      if (o.label) {
        lab = el("text", {x: -w / 2, y: -h / 2 - 26, "font-weight": 800, "font-size": o.labelSize || 52, fill: this.color("ink")}, g);
        lab.textContent = o.label;
      }
      let val = null;
      if (o.valueText) {
        val = el("text", {x: w / 2, y: -h / 2 - 26, "text-anchor": "end", "font-weight": 900, "font-size": o.labelSize || 52, fill: col}, g);
        val.textContent = o.valueText;
      }
      const v = clamp(o.value === undefined ? 1 : o.value);
      return this._add(g, Object.assign({enter: "fade", fillDur: o.fillDur || 1.0}, o), (t, it) => {
        const k = E.out((t - it.at - 0.15) / it.fillDur);
        fill.setAttribute("width", Math.max(0, (w - 16) * v * k));
      });
    }

    // Comparaison de grandeurs : barres verticales qui montent.
    columns(items, o = {}) {
      const g = el("g", {});
      const n = items.length, gap = o.gap || 40, w = o.w || 820, hmax = o.h || 640;
      const bw = (w - gap * (n - 1)) / n, max = Math.max(...items.map((i) => +i.value)) || 1;
      const bars = items.map((itm, i) => {
        const x = -w / 2 + i * (bw + gap);
        const col = this.color(itm.color || (i === n - 1 ? "accent" : "muted"));
        const r = el("rect", {x, y: 0, width: bw, height: 0, rx: 14, fill: col}, g);
        const v = el("text", {x: x + bw / 2, y: 0, "text-anchor": "middle", "font-weight": 900, "font-size": o.valueSize || 64, fill: col}, g);
        const l = el("text", {x: x + bw / 2, y: 70, "text-anchor": "middle", "font-weight": 800, "font-size": o.labelSize || 46, fill: this.color("ink")}, g);
        l.textContent = itm.label;
        return {r, v, h: hmax * (+itm.value / max), txt: itm.valueText || String(itm.value), delay: i * (o.stagger || 0.35)};
      });
      return this._add(g, Object.assign({enter: "fade"}, o), (t, it) => {
        for (const b of bars) {
          const k = E.back((t - it.at - b.delay) / 0.8);
          const h = Math.max(0, b.h * k);
          b.r.setAttribute("y", -h); b.r.setAttribute("height", h);
          b.v.setAttribute("y", -h - 24); b.v.textContent = b.txt; b.v.setAttribute("opacity", clamp((t - it.at - b.delay - 0.4) * 3));
        }
      });
    }

    // Carte du monde (Natural Earth 1:110m). o.center [lon, lat], o.mapScale (200 = monde, 1500 = pays),
    // o.highlight {"France": "accent"}, o.points [{lon, lat, label}], o.route [[lon, lat], …] (tracée progressivement).
    map(o = {}) {
      if (!window.d3 || !window.topojson || !window.WORLD_110M) throw new Error("map() : inclure lib/d3.min.js, lib/topojson-client.min.js et lib/world-110m.js avant studio.js");
      const g = el("g", {});
      const proj = d3.geoMercator().center(o.center || [10, 30]).scale(o.mapScale || 300).translate([0, 0]);
      const path = d3.geoPath(proj);
      const countries = topojson.feature(WORLD_110M, WORLD_110M.objects.countries).features;
      const hl = o.highlight || {};
      for (const f of countries) {
        const name = f.properties.name;
        if (name === "Antarctica" && !hl[name]) continue;
        el("path", {d: path(f) || "", fill: hl[name] ? this.color(hl[name]) : (o.land || "#3A3848"), stroke: this.th.bg, "stroke-width": 1.5}, g);
      }
      const extra = [];
      if (o.route) {
        const pts = o.route.map((c) => proj(c));
        const d = "M" + pts.map((p) => p.join(" ")).join(" L");
        const r = el("path", {d, fill: "none", stroke: this.color("accent"), "stroke-width": 8, "stroke-dasharray": "2 20", "stroke-linecap": "round"}, g);
        extra.push(r);
      }
      const pins = (o.points || []).map((p, i) => {
        const [x, y] = proj([p.lon, p.lat]);
        const pg = el("g", {transform: `translate(${x} ${y})`}, g);
        el("circle", {r: 16, fill: this.color("accent"), stroke: "#fff", "stroke-width": 5}, pg);
        if (p.label) {
          const tx = el("text", {x: 0, y: -34, "text-anchor": "middle", "font-weight": 800, "font-size": p.size || 46, fill: this.color("ink"), stroke: this.th.bg, "stroke-width": 8, "paint-order": "stroke"}, pg);
          tx.textContent = p.label.toUpperCase();
        }
        return {pg, delay: p.at !== undefined ? p.at : 0.4 + i * 0.4};
      });
      return this._add(g, Object.assign({enter: "fade", x: 540, y: o.y || 760, bleed: true}, o, {scale: 1}), (t, it) => {
        for (const p of pins) p.pg.setAttribute("opacity", clamp((t - it.at - p.delay) * 4));
        for (const r of extra) {
          // Pointillés révélés progressivement : motif « 2 20 » répété jusqu'à la longueur parcourue.
          const len = r.getTotalLength(), k = E.inOut((t - it.at - (o.routeAt || 0.6)) / (o.routeDur || 1.4));
          const shown = len * k, reps = Math.floor(shown / 22);
          r.setAttribute("stroke-dasharray", (reps > 0 ? Array(reps).fill("2 20").join(" ") + " " : "") + `0 ${len + 40}`);
          r.setAttribute("opacity", k > 0 ? 1 : 0);
        }
      });
    }

    // Tableau d'unités : count icônes qui apparaissent une à une (ex. 25 crânes = 25 morts).
    // o.lit = nombre d'unités « allumées » (les autres sont estompées), o.cols, o.size, o.stagger.
    units(name, count, o = {}) {
      const g = el("g", {});
      const cols = o.cols || Math.min(count, 10), size = o.size || 80, gap = o.gap || size * 0.18;
      const rows = Math.ceil(count / cols), w = cols * size + (cols - 1) * gap, h = rows * size + (rows - 1) * gap;
      const lit = o.lit === undefined ? count : o.lit;
      const cells = [];
      for (let i = 0; i < count; i++) {
        const cx = -w / 2 + (i % cols) * (size + gap) + size / 2, cy = -h / 2 + Math.floor(i / cols) * (size + gap) + size / 2;
        const c = el("g", {}, g);
        iconImage(name, size, c);
        cells.push({c, cx, cy, on: i < lit});
      }
      const stagger = o.stagger === undefined ? Math.min(0.08, 1.6 / Math.max(count, 1)) : o.stagger;
      return this._add(g, Object.assign({enter: "none"}, o), (t, it) => {
        cells.forEach((cell, i) => {
          const k = E.back((t - it.at - i * stagger) / 0.3);
          cell.c.setAttribute("transform", `translate(${cell.cx} ${cell.cy}) scale(${Math.max(0, k)})`);
          cell.c.setAttribute("opacity", cell.on ? 1 : 0.22);
        });
      });
    }

    // Jauge semi-circulaire persistante (enjeu visible en permanence). o.from / o.to (0-1), o.label, o.moveAt, o.moveDur.
    gauge(o = {}) {
      const g = el("g", {});
      const r = o.r || 110, col = this.color(o.color || "accent");
      el("path", {d: `M${-r} 0 A${r} ${r} 0 0 1 ${r} 0`, fill: "none", stroke: this.th.muted, "stroke-opacity": 0.35, "stroke-width": 22, "stroke-linecap": "round"}, g);
      const arc = el("path", {d: `M${-r} 0 A${r} ${r} 0 0 1 ${r} 0`, fill: "none", stroke: col, "stroke-width": 22, "stroke-linecap": "round"}, g);
      const needle = el("line", {x1: 0, y1: 0, x2: -r * 0.8, y2: 0, stroke: this.th.ink, "stroke-width": 10, "stroke-linecap": "round"}, g);
      el("circle", {r: 16, fill: this.th.ink}, g);
      if (o.label) {
        const l = el("text", {x: 0, y: 64, "text-anchor": "middle", "font-weight": 800, "font-size": o.labelSize || 40, fill: col, "letter-spacing": 3}, g);
        l.textContent = o.label.toUpperCase();
      }
      const len = Math.PI * r, from = clamp(o.from || 0), to = clamp(o.to === undefined ? from : o.to);
      return this._add(g, Object.assign({x: 170, y: 300, scale: 0.8, enter: "pop"}, o), (t, it) => {
        const v = from + (to - from) * E.inOut((t - (o.moveAt === undefined ? it.at + 0.4 : o.moveAt)) / (o.moveDur || 1.2));
        arc.setAttribute("stroke-dasharray", `${len * v} ${len}`);
        needle.setAttribute("transform", `rotate(${180 * v})`);
      });
    }

    // Groupe libre : construire soi-même du SVG via fn(g, el, theme) puis l'animer comme un élément.
    custom(fn, o = {}) {
      const g = el("g", {});
      const update = fn(g, el, this.th) || null;
      return this._add(g, o, update ? (t, it) => update(t - it.at, t) : null);
    }

    // ── effets globaux ──
    camera(o = {}) { this.cams.push(Object.assign({at: 0, dur: 1.2, zoom: 1.25, x: 540, y: 900}, o)); return this; }
    shake(o = {}) { this.shakes.push(Object.assign({at: 0, dur: 0.4, amp: 18}, o)); return this; }
    flash(o = {}) { this.flashes.push(Object.assign({at: 0, dur: 0.18}, o)); return this; }

    _fit() {
      for (const it of this.items) {
        if (it.boxed) {
          const bb = it.boxed.n.getBBox(), p = it.boxed.pad;
          it.boxed.rect.setAttribute("x", bb.x - p); it.boxed.rect.setAttribute("y", bb.y - p * 0.5);
          it.boxed.rect.setAttribute("width", bb.width + 2 * p); it.boxed.rect.setAttribute("height", bb.height + p);
        }
        if (it.fit) {
          for (const n of it.fit) {
            if (!n) continue;
            const w = n.getComputedTextLength ? n.getComputedTextLength() : 0;
            if (w > it.maxW) n.setAttribute("font-size", parseFloat(n.getAttribute("font-size")) * it.maxW / w);
          }
        }
      }
      this.fitted = true;
    }

    render(t) {
      if (!this.fitted) this._fit();
      for (const it of this.items) {
        const k = this._apply(it, t);
        if (k >= 0 && it.update) it.update(t, it);
        if (k >= 0 && it.update && it.x !== undefined) this._apply(it, t);
      }
      // Caméra : zooms successifs (le dernier commencé l'emporte), centrés sur (x, y).
      let z = 1, cx = 540, cy = 960;
      for (const c of this.cams) {
        if (t < c.at) continue;
        const k = E.inOut((t - c.at) / c.dur);
        z = z + (c.zoom - z) * k; cx = cx + (c.x - cx) * k; cy = cy + (c.y - cy) * k;
      }
      let sx = 0, sy = 0;
      for (const s of this.shakes) {
        if (t >= s.at && t < s.at + s.dur) {
          const d = 1 - (t - s.at) / s.dur;
          sx += Math.sin(t * 91) * s.amp * d; sy += Math.cos(t * 77) * s.amp * d;
        }
      }
      this.world.setAttribute("transform", `translate(${540 + sx} ${960 + sy}) scale(${z}) translate(${-cx} ${-cy})`);
      let f = 0;
      for (const fl of this.flashes) if (t >= fl.at && t < fl.at + fl.dur) f = Math.max(f, 0.35 * (1 - (t - fl.at) / fl.dur));
      this.flashRect.setAttribute("opacity", f);
    }
  }

  window.Studio = {scene: (o) => new Scene(o), THEMES, ease: E};
})();

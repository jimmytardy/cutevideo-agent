/* studio3d.js — motion design 3D des Shorts (three.js, rendu logiciel déterministe 1080×1920).
 *
 *   <script src="lib/three.bundle.min.js"></script>
 *   <script src="lib/fonts/poppins3d.typeface.js"></script>   (seulement pour number())
 *   <script src="lib/studio.js"></script>
 *   <script src="lib/studio3d.js"></script>
 *   <script>
 *   const s = Studio3D.scene({theme: "night", accent: "#FF5A1F", floor: "gloss", bloom: 0.6, dof: true});
 *   const ui = Studio.scene({theme: "night", accent: "#FF5A1F", transparent: true});   // titres SVG nets
 *   ui.title("12 000 PAS", {sub: "par jour"});
 *   s.phone({screen: (c, t, k) => k.ring(c, 0.5, 0.42, 0.3, Math.min(1, t / 2), "84 %"), idle: "float"});
 *   s.ring({r: 1.5});
 *   s.orbit({at: 0, dur: 4, from: -25, to: 20});
 *   </script>
 *
 * Monde en mètres : sol en y = 0, objets centrés en x = 0, caméra par défaut à 9,5 m visant (0, 0.8, 0). Le
 * centre optique est décalé vers le haut de l'écran (zone utile y 170-1180) : le point visé tombe à y ≈ 790 (sous le titre SVG).
 * Tout est fonction de t (renderFrame posé par Studio.register) : aucune horloge, aucun Math.random.
 * Options communes : at, dur, enter (none|pop|rise|drop|spin|slide|flip|fade), out + exit (fade|pop|sink),
 * idle (float|spin|sway|pulse), x, y, z, rx, ry, rz (radians), scale, bleed (hors zone voulu : pas d'alerte).
 */
(function () {
  "use strict";
  if (!window.THREE) throw new Error("studio3d.js : inclure lib/three.bundle.min.js avant");
  if (!window.Studio) throw new Error("studio3d.js : inclure lib/studio.js avant");
  const T = window.THREE;
  const W = 1080, H = 1920;
  const E = Studio.ease;
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, k) => a + (b - a) * k;
  const EASES = {linear: (x) => clamp(x), out: E.out, inOut: E.inOut, back: E.back, elastic: E.elastic};
  // Centre optique visé (px) : milieu de la zone utile, au-dessus des sous-titres.
  const OPTICAL_Y = 790;

  // Aléatoire déterministe (même image à chaque rendu).
  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let x = Math.imul(a ^ (a >>> 15), 1 | a);
      x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
      return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
    };
  }

  const ENVS = {
    // key : lumière principale ; rim : contre-jour teinté de l'accent ; env : intensité des reflets.
    studio: {key: 0xffffff, keyI: 300, rimI: 3.5, edgeI: 2.2, fill: 0.3, env: 1.1, sky: null},
    night: {key: 0xdfe6ff, keyI: 240, rimI: 4, edgeI: 1.6, fill: 0.2, env: 0.9, sky: null},
    sunset: {key: 0xffb37a, keyI: 340, rimI: 2, edgeI: 2.5, fill: 0.4, env: 1.0, sky: ["#2a1410", "#c8642c", "#f6c48a"]},
  };

  function canvasTexture(w, h) {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const tex = new T.CanvasTexture(c);
    tex.colorSpace = T.SRGBColorSpace;
    tex.anisotropy = 4;
    return {c, ctx: c.getContext("2d"), tex};
  }

  // Petits outils de dessin pour les écrans et cartes (coordonnées 0-1 de la surface).
  function uiKit(th) {
    const font = (px, w = 800) => `${w} ${px}px Studio, "DejaVu Sans", sans-serif`;
    const col = (c) => c === "accent" ? th.accent : c === "accent2" ? th.accent2 : c === "muted" ? th.muted : c === "ink" ? th.ink : (c || th.ink);
    return {
      font, color: col,
      bg(ctx, color) { ctx.fillStyle = color || "#0d0d12"; ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height); },
      text(ctx, s, x, y, o = {}) {
        const c = ctx.canvas;
        ctx.font = font((o.size || 0.06) * c.width, o.weight || 800);
        ctx.fillStyle = col(o.color || "ink");
        ctx.textAlign = o.align || "left";
        ctx.textBaseline = o.baseline || "alphabetic";
        ctx.fillText(String(s), x * c.width, y * c.height);
      },
      // Anneau de progression (k 0-1) avec valeur au centre.
      ring(ctx, x, y, r, k, label, o = {}) {
        const c = ctx.canvas, R = r * c.width, cx = x * c.width, cy = y * c.height;
        ctx.lineCap = "round";
        ctx.lineWidth = R * 0.16;
        ctx.strokeStyle = "rgba(255,255,255,0.10)";
        ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
        ctx.strokeStyle = col(o.color || "accent");
        ctx.beginPath(); ctx.arc(cx, cy, R, -Math.PI / 2, -Math.PI / 2 + clamp(k) * Math.PI * 2); ctx.stroke();
        if (label !== undefined) this.text(ctx, label, x, y + r * 0.12 * c.width / c.height, {size: r * 0.55, align: "center", weight: 900});
      },
      // Lignes de liste qui apparaissent une à une (k 0-1 = progression).
      rows(ctx, items, k, o = {}) {
        const c = ctx.canvas, y0 = o.y || 0.3, h = o.h || 0.1;
        items.forEach((it, i) => {
          const a = clamp(k * items.length - i);
          if (a <= 0) return;
          const y = (y0 + i * (h + 0.015)) * c.height;
          ctx.globalAlpha = a;
          ctx.fillStyle = it.color ? col(it.color) : "rgba(255,255,255,0.07)";
          roundRect(ctx, 0.07 * c.width, y, 0.86 * c.width, h * c.height, 0.035 * c.width); ctx.fill();
          this.text(ctx, it.text || it, 0.12, (y + h * c.height * 0.64) / c.height, {size: 0.075, color: it.ink || "ink"});
          if (it.value) this.text(ctx, it.value, 0.88, (y + h * c.height * 0.64) / c.height, {size: 0.075, align: "right", color: "accent"});
          ctx.globalAlpha = 1;
        });
      },
      bars(ctx, values, k, o = {}) {
        const c = ctx.canvas, n = values.length, x0 = 0.1, w = 0.8, gap = 0.03, base = o.y || 0.85, hmax = o.h || 0.3;
        const bw = (w - gap * (n - 1)) / n, max = Math.max(...values) || 1;
        values.forEach((v, i) => {
          const h = hmax * (v / max) * E.back(k * 1.4 - i * 0.12);
          ctx.fillStyle = i === n - 1 ? col("accent") : "rgba(255,255,255,0.18)";
          roundRect(ctx, (x0 + i * (bw + gap)) * c.width, (base - Math.max(0, h)) * c.height, bw * c.width, Math.max(0, h) * c.height, 0.02 * c.width);
          ctx.fill();
        });
      },
      button(ctx, label, y, o = {}) {
        const c = ctx.canvas;
        ctx.fillStyle = col(o.color || "accent");
        roundRect(ctx, 0.12 * c.width, y * c.height, 0.76 * c.width, 0.075 * c.height, 0.0375 * c.height); ctx.fill();
        this.text(ctx, label, 0.5, y + 0.05, {size: 0.06, align: "center", color: o.ink || "#111"});
      },
    };
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  // Post-traitement en une chaîne courte, taillée pour le rendu logiciel (SwiftShader) où chaque passe plein
  // écran coûte cher : la scène est rendue une fois (HDR + profondeur), réduite au quart, floutée (profondeur
  // de champ) et seuillée/floutée (halo), puis UNE passe pleine résolution fait tout le reste — mélange net/flou
  // selon la distance de mise au point, halo, tone mapping ACES, sRGB, vignettage, grain et anticrénelage FXAA.
  // (EffectComposer + BokehPass + UnrealBloom + MSAA : ~4× plus lent pour un rendu équivalent.)
  const VS = "varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }";
  const BLUR_FS = `uniform sampler2D src; uniform vec2 dir; varying vec2 vUv;
    void main(){ vec4 c = texture2D(src, vUv) * 0.227;
      c += (texture2D(src, vUv + dir * 1.385) + texture2D(src, vUv - dir * 1.385)) * 0.316;
      c += (texture2D(src, vUv + dir * 3.231) + texture2D(src, vUv - dir * 3.231)) * 0.070;
      gl_FragColor = c; }`;
  const FINAL_FS = `uniform sampler2D sharp; uniform sampler2D soft; uniform sampler2D glow; uniform sampler2D glow2; uniform sampler2D depth;
    uniform vec2 px; uniform float near; uniform float far; uniform float focus; uniform float range; uniform float dofOn;
    uniform float bloom; uniform float exposure; uniform float vignette; uniform float grain; uniform float seed;
    varying vec2 vUv;
    vec3 rrt(vec3 v){ vec3 a = v * (v + 0.0245786) - 0.000090537; vec3 b = v * (0.983729 * v + 0.4329510) + 0.238081; return a / b; }
    vec3 aces(vec3 c){
      const mat3 I = mat3(vec3(0.59719, 0.07600, 0.02840), vec3(0.35458, 0.90834, 0.13383), vec3(0.04823, 0.01566, 0.83777));
      const mat3 O = mat3(vec3(1.60475, -0.10208, -0.00327), vec3(-0.53108, 1.10813, -0.07276), vec3(-0.07367, -0.00605, 1.07602));
      return clamp(O * rrt(I * c), 0.0, 1.0); }
    // ACES blanchit les couleurs saturées en montant (orange → jaune → blanc) : on mêle la même courbe appliquée
    // au canal le plus fort, qui garde la teinte (l'orange reste orange au cœur d'un anneau).
    vec3 tonemap(vec3 c){ c *= exposure / 0.6; float m = max(c.r, max(c.g, c.b));
      vec3 hp = c * (aces(vec3(m)).g / max(m, 1e-5)); return mix(aces(c), clamp(hp, 0.0, 1.0), 0.6); }
    vec3 srgb(vec3 c){ return mix(c * 12.92, pow(c, vec3(1.0 / 2.4)) * 1.055 - 0.055, step(0.0031308, c)); }
    float luma(vec3 c){ return dot(c, vec3(0.299, 0.587, 0.114)); }
    float edge(vec2 uv){ float l = luma(texture2D(sharp, uv).rgb); return l / (1.0 + l); }
    float hash(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233)) + seed) * 43758.5453); }
    void main(){
      // FXAA allégé : arêtes détectées sur la luminance de l'image nette, puis lissage de l'image HDR le long de
      // l'arête AVANT le reste de la chaîne (une seule évaluation de profondeur de champ, halo et tone mapping).
      vec3 c = texture2D(sharp, vUv).rgb;
      float lN = edge(vUv + vec2(0.0, px.y)), lS = edge(vUv - vec2(0.0, px.y));
      float lE = edge(vUv + vec2(px.x, 0.0)), lW = edge(vUv - vec2(px.x, 0.0)), lM = edge(vUv);
      float span = max(max(max(lN, lS), max(lE, lW)), lM) - min(min(min(lN, lS), min(lE, lW)), lM);
      if (span > 0.06) {
        vec2 dir = normalize(vec2(-((lN + lS) - (lE + lW)), (lE + lW) - (lN + lS)) + 1e-4) * px;
        c = mix(c, 0.5 * (texture2D(sharp, vUv + dir * 0.5).rgb + texture2D(sharp, vUv - dir * 0.5).rgb), 0.65);
      }
      if (dofOn > 0.5) {
        float d = texture2D(depth, vUv).x;
        float z = (near * far) / (far - d * (far - near));
        c = mix(c, texture2D(soft, vUv).rgb, smoothstep(0.0, 1.0, abs(z - focus) / range));
      }
      // Halo : cœur serré (1/4) + nappe large (1/8), comme une lumière réelle.
      vec3 halo = texture2D(glow, vUv).rgb * 0.55 + texture2D(glow2, vUv).rgb * 0.9;
      c = srgb(tonemap(c + halo * bloom));
      vec2 dv = vUv - vec2(0.5, 0.55);
      c *= mix(1.0 - vignette, 1.0, smoothstep(0.85, 0.25, length(dv * vec2(1.0, 0.8))));
      c += (hash(vUv * 1000.0) - 0.5) * grain;
      gl_FragColor = vec4(c, 1.0);
    }`;

  // Reflet du sol : la couleur de l'objet atténuée, qui s'éteint en s'éloignant du sujet vers la caméra. (Le
  // ReflectorShader de three mélange en « overlay » : il écrase les canaux sous 0.5 et amplifie le HDR — un orange
  // devenait un rouge saturé plus lumineux que l'objet.)
  const REFLECT_SHADER = {
    name: "StudioReflector",
    uniforms: {color: {value: null}, tDiffuse: {value: null}, textureMatrix: {value: null}, strength: {value: 0.6},
      uCam: {value: new T.Vector2(0, 9)}, uTarget: {value: new T.Vector2()}},
    vertexShader: `uniform mat4 textureMatrix; varying vec4 vUv; varying vec3 vWorld;
      void main(){ vUv = textureMatrix * vec4(position, 1.0); vWorld = (modelMatrix * vec4(position, 1.0)).xyz;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform sampler2D tDiffuse; uniform float strength; uniform vec2 uCam; uniform vec2 uTarget;
      varying vec4 vUv; varying vec3 vWorld;
      void main(){ vec3 base = texture2DProj(tDiffuse, vUv).rgb;
        float d = dot(vWorld.xz - uTarget, normalize(uCam - uTarget + 1e-4));
        gl_FragColor = vec4(base * strength * (1.0 - smoothstep(0.1, 2.4, d)), 1.0); }`,
  };

  class Post {
    constructor(renderer, w, h, o) {
      this.r = renderer;
      this.scene = new T.WebGLRenderTarget(w, h, {type: T.HalfFloatType, depthTexture: new T.DepthTexture(w, h)});
      const small = {type: T.HalfFloatType};
      this.a = new T.WebGLRenderTarget(Math.ceil(w / 4), Math.ceil(h / 4), small);
      this.b = this.a.clone();
      this.g = this.a.clone();
      this.g2 = new T.WebGLRenderTarget(Math.ceil(w / 8), Math.ceil(h / 8), small);
      this.b2 = this.g2.clone();
      this.cam = new T.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      this.quad = new T.Mesh(new T.PlaneGeometry(2, 2));
      this.copy = new T.ShaderMaterial({uniforms: {src: {value: null}}, vertexShader: VS,
        fragmentShader: "uniform sampler2D src; varying vec2 vUv; void main(){ gl_FragColor = texture2D(src, vUv); }"});
      this.bright = new T.ShaderMaterial({uniforms: {src: {value: null}, threshold: {value: o.threshold}}, vertexShader: VS,
        fragmentShader: `uniform sampler2D src; uniform float threshold; varying vec2 vUv;
          void main(){ vec3 c = texture2D(src, vUv).rgb; float l = max(c.r, max(c.g, c.b));
            gl_FragColor = vec4(c * smoothstep(threshold, threshold + 0.6, l), 1.0); }`});
      this.blurMat = new T.ShaderMaterial({uniforms: {src: {value: null}, dir: {value: new T.Vector2()}}, vertexShader: VS, fragmentShader: BLUR_FS});
      this.final = new T.ShaderMaterial({vertexShader: VS, fragmentShader: FINAL_FS, uniforms: {
        sharp: {value: this.scene.texture}, soft: {value: this.a.texture}, glow: {value: this.g.texture}, glow2: {value: this.g2.texture},
        depth: {value: this.scene.depthTexture},
        px: {value: new T.Vector2(1 / w, 1 / h)}, near: {value: 0.1}, far: {value: 100}, focus: {value: 8},
        range: {value: 4.0 / (o.dof || 1)}, dofOn: {value: o.dof ? 1 : 0}, bloom: {value: o.bloom},
        exposure: {value: o.exposure}, vignette: {value: o.vignette}, grain: {value: 0.015}, seed: {value: 0}}});
    }
    _draw(mat, target) { this.quad.material = mat; this.r.setRenderTarget(target); this.r.render(this.quad, this.cam); }
    _blur(target, tmp, passes, spread) {
      for (let i = 0; i < passes; i++) {
        const k = spread * (i + 1);
        this.blurMat.uniforms.src.value = target.texture; this.blurMat.uniforms.dir.value.set(k / target.width, 0);
        this._draw(this.blurMat, tmp);
        this.blurMat.uniforms.src.value = tmp.texture; this.blurMat.uniforms.dir.value.set(0, k / target.height);
        this._draw(this.blurMat, target);
      }
    }
    render(scene, cam, t) {
      const u = this.final.uniforms;
      this.r.setRenderTarget(this.scene);
      this.r.render(scene, cam);
      if (u.dofOn.value || u.bloom.value > 0) { this.copy.uniforms.src.value = this.scene.texture; this._draw(this.copy, this.a); }
      if (u.bloom.value > 0) {
        this.bright.uniforms.src.value = this.a.texture;
        this._draw(this.bright, this.g);
        this._blur(this.g, this.b, 3, 1.0);
        this.copy.uniforms.src.value = this.g.texture;
        this._draw(this.copy, this.g2);
        this._blur(this.g2, this.b2, 2, 1.5);
      }
      if (u.dofOn.value) this._blur(this.a, this.b, 2, 1.0);
      u.near.value = cam.near; u.far.value = cam.far; u.seed.value = (t * 37.17) % 100;
      this._draw(this.final, null);
    }
  }

  class Scene3D {
    constructor(o = {}) {
      Studio.fonts();
      this.o = o;
      this.th = Object.assign({}, Studio.THEMES[o.theme || "night"] || Studio.THEMES.night);
      if (o.accent) this.th.accent = o.accent;
      if (o.accent2) this.th.accent2 = o.accent2;
      this.ui = uiKit(this.th);
      this.env = ENVS[o.env || "studio"] || ENVS.studio;
      this.items = [];
      this.moves = [];
      this.shakes = [];
      this.pending = [];
      this.start = {pos: [0, 1.5, 9.5], target: [0, 0.8, 0], fov: 28};
      if (o.camera) Object.assign(this.start, o.camera);

      const quality = clamp(o.quality === undefined ? 1 : +o.quality, 0.4, 1);
      const r = new T.WebGLRenderer({antialias: false, preserveDrawingBuffer: true, powerPreference: "high-performance"});
      if (!r.getContext()) throw new Error("WebGL indisponible : la 3D exige animate --3d (chaîne en motion design 3D)");
      r.setPixelRatio(quality);
      r.setSize(W, H);
      // Tone mapping et sRGB sont appliqués par la passe finale (Post) : la scène est rendue en HDR linéaire.
      // Un shader qui ne compile pas (custom(), matière maison) doit faire échouer le rendu, pas donner une image noire.
      r.debug.onShaderError = (gl, program, vs, fs) => {
        throw new Error(`shader invalide : ${(gl.getShaderInfoLog(fs) || gl.getShaderInfoLog(vs) || gl.getProgramInfoLog(program) || "").slice(0, 400)}`);
      };
      r.shadowMap.enabled = o.shadows !== false;
      r.shadowMap.type = T.PCFShadowMap;
      r.domElement.style.cssText = "position:absolute;left:0;top:0;z-index:1";
      document.body.appendChild(r.domElement);
      this.renderer = r;

      const scene = new T.Scene();
      this.scene = scene;
      // Fond et brouillard de la même couleur à l'horizon : pas de couture entre le sol et le fond.
      this.horizon = new T.Color(this.th.bg).lerp(new T.Color(this.th.bg2), 0.6);
      scene.background = this._backdrop();
      scene.fog = new T.Fog(this.horizon, o.fogNear || 11, o.fogFar || 24);
      const pm = new T.PMREMGenerator(r);
      scene.environment = this._studioEnv(pm);
      scene.environmentIntensity = this.env.env;
      pm.dispose();

      this.cam = new T.PerspectiveCamera(this.start.fov, W / H, 0.1, 100);
      this.cam.setViewOffset(W, H, 0, H / 2 - OPTICAL_Y, W, H);

      this._lights();
      this._floor(o.floor === undefined ? "gloss" : o.floor);

      const bloom = o.bloom === undefined ? 0.3 : +o.bloom;
      this.post = new Post(r, Math.round(W * quality), Math.round(H * quality), {
        dof: o.dof ? (typeof o.dof === "number" ? o.dof : 1) : 0, bloom, threshold: o.threshold || 2.2,
        exposure: o.exposure || 1.0, vignette: o.vignette === undefined ? 0.45 : o.vignette});
      Studio.register(this);
    }

    color(c) { return new T.Color(this.ui.color(c)); }

    _backdrop() {
      const {c, ctx, tex} = canvasTexture(256, 512);
      const sky = this.env.sky;
      if (sky) {
        const g = ctx.createLinearGradient(0, 0, 0, 512);
        g.addColorStop(0, sky[0]); g.addColorStop(0.55, sky[1]); g.addColorStop(1, sky[2]);
        ctx.fillStyle = g;
      } else {
        const g = ctx.createLinearGradient(0, 0, 0, 512), hz = `#${this.horizon.getHexString()}`;
        g.addColorStop(0, this.th.bg); g.addColorStop(0.32, hz); g.addColorStop(1, hz);
        ctx.fillStyle = g;
      }
      ctx.fillRect(0, 0, c.width, c.height);
      return tex;
    }

    // Environnement de reflets « studio » : du noir et quelques panneaux lumineux. Ce sont leurs filets de lumière
    // le long des arêtes qui font le rendu « produit » (une pièce grise uniforme donne un aspect pâte à modeler).
    _studioEnv(pm) {
      const sc = new T.Scene(), geo = new T.PlaneGeometry(1, 1);
      const panel = (w, h, i, col, p) => {
        const m = new T.Mesh(geo, new T.MeshBasicMaterial({color: new T.Color(col).multiplyScalar(i), side: T.DoubleSide}));
        m.scale.set(w, h, 1); m.position.set(...p); m.lookAt(0, 1, 0); sc.add(m);
      };
      panel(5, 1.2, 8, 0xffffff, [1.5, 6, 3]);         // boîte à lumière haute : filet sur les dessus et biseaux
      panel(0.8, 4, 5, 0xffffff, [-5, 2.5, 1.5]);      // bande gauche : arête verticale (tranche du téléphone)
      panel(0.8, 4, 3, 0xffffff, [5, 2.5, -1]);        // bande droite, plus faible
      panel(6, 1.5, 3, this.th.accent, [0, 1.5, -6]);  // touche d'accent derrière : reflet teinté sur les faces inclinées
      return pm.fromScene(sc, 0.02).texture;
    }

    _lights() {
      const s = this.scene, env = this.env;
      // Cône serré, pénombre large : une flaque de lumière douce autour du sujet, le reste du sol dans l'ombre.
      const key = new T.SpotLight(env.key, env.keyI, 30, 0.36, 0.95, 1.6);
      key.position.set(3.2, 7.5, 4.5);
      key.target.position.set(0, 0.8, 0);
      key.castShadow = this.renderer.shadowMap.enabled;
      // Carte réduite + rayon : ombre douce (PCF honore radius en r170, à nombre de lectures fixe).
      key.shadow.mapSize.set(512, 512);
      key.shadow.radius = 5;
      key.shadow.bias = -0.0005;
      key.shadow.camera.near = 3;
      key.shadow.camera.far = 16;
      s.add(key, key.target);
      // Contre-jours : projecteur teinté de l'accent derrière le sujet (halo coloré au sol derrière lui, sans
      // teinter tout le sol) et lumière blanche à droite — ils détachent les arêtes du fond sombre.
      const rim = new T.SpotLight(this.th.accent, env.rimI * 14, 16, 0.42, 0.9, 1.4);
      rim.position.set(-3.5, 3.2, -5);
      rim.target.position.set(0, 0.9, 0);
      s.add(rim.target);
      const edge = new T.DirectionalLight(0xffffff, env.edgeI);
      edge.position.set(5, 4, -3);
      s.add(rim, edge);
      s.add(new T.HemisphereLight(0xffffff, this.th.bg, env.fill));
      this.key = key;
    }

    // Le sol couvre la moitié de l'image : un matériau PBR y coûterait ~2 s par image en rendu logiciel. Lambert
    // (éclairage diffus, ombres) + un reflet rendu en basse résolution sous un voile : le flou de la basse
    // résolution donne naturellement le brillant doux d'un sol de studio. gloss = reflet doux, mirror = net.
    _floor(kind) {
      if (!kind || kind === "none") return;
      // Presque noir : seule la flaque du projecteur se lit, puis le brouillard l'éteint vers l'horizon.
      const base = new T.Color(this.th.bg).lerp(new T.Color(this.th.bg2), 0.45);
      const mat = new T.MeshLambertMaterial({color: base});
      const floor = new T.Mesh(new T.PlaneGeometry(80, 80), mat);
      floor.rotation.x = -Math.PI / 2;
      floor.receiveShadow = true;
      if (kind === "gloss" || kind === "mirror") {
        const div = kind === "mirror" ? 2 : 6;
        // multisample 0 : le MSAA caché du Reflector coûterait cher en rendu logiciel.
        const mirror = new T.Reflector(new T.PlaneGeometry(80, 80), {textureWidth: W / div, textureHeight: H / div,
          shader: REFLECT_SHADER, multisample: 0});
        mirror.rotation.x = -Math.PI / 2;
        mirror.position.y = -0.002;
        this.scene.add(mirror);
        this.mirror = mirror;
        mat.transparent = true;
        mat.opacity = kind === "mirror" ? 0.5 : 0.65;
      }
      this.scene.add(floor);
      if (kind === "grid") {
        const grid = new T.GridHelper(40, 40, this.th.accent, this.th.muted);
        grid.material.transparent = true;
        grid.material.opacity = 0.16;
        grid.position.y = 0.002;
        this.scene.add(grid);
      }
    }

    // ── mécanique commune ──
    _add(obj, o, update) {
      const it = Object.assign({at: 0, dur: 0.6, enter: "pop", exit: "fade", exitDur: 0.4, x: 0, y: 0, z: 0, rx: 0, ry: 0, rz: 0, scale: 1},
        o, {obj, update, label: o.label || obj.name || "objet"});
      obj.traverse((m) => {
        if (m.isMesh) { m.castShadow = o.shadow !== false; m.receiveShadow = true; }
      });
      if (["fade"].includes(it.enter) || it.out !== undefined) this._fadeable(obj);
      this.scene.add(obj);
      this.items.push(it);
      return it;
    }

    _fadeable(obj) {
      obj.traverse((m) => {
        if (!m.material) return;
        for (const mat of [].concat(m.material)) { mat.transparent = true; mat.userData.op = mat.opacity; }
      });
    }

    _opacity(obj, op) {
      obj.traverse((m) => {
        if (!m.material) return;
        for (const mat of [].concat(m.material)) if (mat.transparent) mat.opacity = (mat.userData.op ?? 1) * op;
      });
    }

    _apply(it, t) {
      const o = it.obj;
      if (t < it.at || (it.out !== undefined && t >= it.out + it.exitDur)) { o.visible = false; return -1; }
      o.visible = true;
      const k = (t - it.at) / it.dur, e = E.out(k), b = E.back(k);
      let x = it.x, y = it.y, z = it.z, rx = it.rx, ry = it.ry, rz = it.rz, sc = it.scale, op = 1;
      if (it.track) ({x, y, z, rx, ry, rz, scale: sc} = Object.assign({x, y, z, rx, ry, rz, scale: sc}, it.track(t)));
      switch (it.enter) {
        case "pop": sc *= Math.max(0.001, b); break;
        case "rise": y -= (1 - e) * 1.4; rx += (1 - e) * 0.35; sc *= 0.7 + 0.3 * e; break;
        case "drop": y += (1 - E.elastic(k)) * 3.5; break;
        case "spin": ry -= (1 - e) * Math.PI * 1.5; sc *= Math.max(0.001, e); break;
        case "slide": x += (1 - e) * (it.from === "left" ? -4 : 4); ry += (1 - e) * (it.from === "left" ? 0.6 : -0.6); break;
        case "flip": rx -= (1 - b) * Math.PI / 2; break;
        case "fade": op *= e; break;
        default: break;
      }
      if (it.out !== undefined && t >= it.out) {
        const q = E.inOut((t - it.out) / it.exitDur);
        if (it.exit === "pop") sc *= Math.max(0.001, 1 - q);
        else if (it.exit === "sink") { y -= q * 1.5; op *= 1 - q; } else op *= 1 - q;
      }
      const life = t - it.at;
      if (it.idle === "float") y += Math.sin(life * 1.8) * 0.06;
      else if (it.idle === "spin") ry += life * 0.6;
      else if (it.idle === "sway") ry += Math.sin(life * 1.2) * 0.22;
      else if (it.idle === "pulse") sc *= 1 + 0.035 * Math.sin(life * 4.5);
      o.position.set(x, y, z);
      o.rotation.set(rx, ry, rz);
      o.scale.setScalar(sc);
      if (op < 1 || it.enter === "fade" || it.out !== undefined) this._opacity(o, clamp(op));
      return clamp(k);
    }

    // Images clés (t absolu) qui pilotent x/y/z/rx/ry/rz/scale d'un élément : s.track(it, [{t: 0, x: 0}, {t: 2, x: 1.5}]).
    track(it, keys, o = {}) {
      const ks = keys.slice().sort((a, b) => a.t - b.t), ease = EASES[o.ease || "inOut"];
      it.track = (t) => {
        if (t <= ks[0].t) return strip(ks[0]);
        for (let i = 1; i < ks.length; i++) {
          if (t <= ks[i].t) {
            const a = ks[i - 1], bb = ks[i], k = ease((t - a.t) / (bb.t - a.t)), out = {};
            for (const p of Object.keys(bb)) if (p !== "t" && a[p] !== undefined) out[p] = lerp(a[p], bb[p], k);
            return Object.assign(strip(a), out);
          }
        }
        return strip(ks[ks.length - 1]);
      };
      return it;
    }

    // ── matières ──
    // PBR sur les objets seulement (ils couvrent peu de pixels) ; clearcoat (vernis, ~+30 %) sur demande.
    gloss(color, o = {}) {
      const opts = Object.assign({color: this.color(color), metalness: 0.15, roughness: 0.28}, o);
      return opts.clearcoat ? new T.MeshPhysicalMaterial(opts) : new T.MeshStandardMaterial(opts);
    }
    metal(color, o = {}) { return new T.MeshStandardMaterial(Object.assign({color: this.color(color), metalness: 0.9, roughness: 0.25}, o)); }
    glow(color, intensity = 4) { return new T.MeshStandardMaterial({color: this.color(color), emissive: this.color(color), emissiveIntensity: intensity}); }

    // ── objets ──
    // Téléphone : écran dessiné à chaque image par screen(ctx, t, ui) (t relatif à l'apparition).
    phone(o = {}) {
      const w = o.w || 0.8, h = w * 2.05, d = w * 0.085;
      const g = new T.Group();
      g.name = "téléphone";
      const body = new T.Mesh(new T.RoundedBoxGeometry(w, h, d, 6, w * 0.12), this.metal(o.color || "#4a4c56", {roughness: 0.22}));
      body.position.y = h / 2;
      g.add(body);
      const scr = canvasTexture(640, 1312);
      // Écran = verre : contenu émissif (blanc à 1.0, sous le seuil du halo, le texte reste net) + reflets de
      // l'environnement de studio qui le balaient quand la caméra tourne.
      const screen = new T.Mesh(new T.PlaneGeometry(w * 0.92, h * 0.955), new T.MeshStandardMaterial({
        color: 0x000000, emissive: 0xffffff, emissiveMap: scr.tex, roughness: 0.06, metalness: 0}));
      screen.position.set(0, h / 2, d / 2 + 0.001);
      g.add(screen);
      const notch = new T.Mesh(new T.CapsuleGeometry(w * 0.035, w * 0.16, 4, 12), new T.MeshBasicMaterial({color: 0x000000}));
      notch.rotation.z = Math.PI / 2;
      notch.position.set(0, h * 0.955, d / 2 + 0.002);
      g.add(notch);
      const draw = o.screen || ((c, t, ui) => { ui.bg(c); ui.ring(c, 0.5, 0.42, 0.3, Math.min(1, t / 2), `${Math.round(Math.min(1, t / 2) * 100)} %`); });
      return this._add(g, Object.assign({ry: -0.18}, o), (t, it) => {
        draw(scr.ctx, t - it.at, this.ui, scr.c);
        scr.tex.needsUpdate = true;
      });
    }

    // Carte flottante (interface, statistique) : face dessinée par face(ctx, t, ui) ou title/value/sub.
    card(o = {}) {
      const w = o.w || 1.6, h = o.h || 1.0, d = o.d || 0.05;
      const g = new T.Group();
      g.name = o.title ? `carte « ${o.title} »` : "carte";
      const fill = o.fill || "#17171f";
      const body = new T.Mesh(new T.RoundedBoxGeometry(w, h, d, 4, Math.min(w, h) * 0.08), this.gloss(fill, {roughness: 0.35}));
      g.add(body);
      const face = canvasTexture(Math.round(512 * w / h), 512);
      const mat = new T.MeshBasicMaterial({map: face.tex, transparent: true});
      const plane = new T.Mesh(new T.PlaneGeometry(w * 0.94, h * 0.9), mat);
      plane.position.z = d / 2 + 0.001;
      g.add(plane);
      const ui = this.ui;
      const draw = o.face || ((c, t) => {
        c.clearRect(0, 0, c.canvas.width, c.canvas.height);
        if (o.title) ui.text(c, o.title, 0.07, 0.24, {size: 0.07 * c.canvas.height / c.canvas.width, color: "muted", weight: 600});
        if (o.value !== undefined) ui.text(c, o.value, 0.07, 0.66, {size: 0.3 * c.canvas.height / c.canvas.width, weight: 900, color: o.valueColor || "ink"});
        if (o.sub) ui.text(c, o.sub, 0.07, 0.88, {size: 0.08 * c.canvas.height / c.canvas.width, color: "accent"});
      });
      let drawn = false;
      return this._add(g, Object.assign({y: 1.2, shadow: false}, o), (t, it) => {
        if (o.face || !drawn) { draw(face.ctx, t - it.at, ui, face.c); face.tex.needsUpdate = true; drawn = true; }
      });
    }

    // Chiffre extrudé (inclure lib/fonts/poppins3d.typeface.js). from/to : compte ; text : fixe ; unit : unité plus
    // petite à droite (« km », « % ») — un nombre long garde ainsi des chiffres hauts.
    number(o = {}) {
      if (!window.POPPINS_3D) throw new Error("number() : inclure lib/fonts/poppins3d.typeface.js avant studio3d.js");
      this._font = this._font || new T.FontLoader().parse(window.POPPINS_3D);
      const size = o.size || 1.0, depth = o.depth || size * 0.28;
      const front = this.gloss(o.color || "accent", {roughness: 0.22});
      const side = this.gloss(o.sideColor || new T.Color(this.ui.color(o.color || "accent")).multiplyScalar(0.45), {roughness: 0.4});
      const text = (str, sz) => {
        const gm = new T.TextGeometry(str, {font: this._font, size: sz, depth: depth * sz / size, curveSegments: 8,
          bevelEnabled: true, bevelThickness: sz * 0.03, bevelSize: sz * 0.02, bevelSegments: 3});
        gm.computeBoundingBox();
        return gm;
      };
      const from = +o.from || 0, to = o.to === undefined ? from : +o.to, dec = o.decimals || 0, cd = o.countDur || 1.4;
      const fmt = (v) => o.text !== undefined ? String(o.text)
        : (o.prefix || "") + v.toLocaleString("fr-FR", {minimumFractionDigits: dec, maximumFractionDigits: dec})
          .replace(/ | /g, " ") + (o.suffix || "");
      const final = fmt(to), unit = o.unit ? String(o.unit).trim() : "";
      const missing = [...new Set(final + unit)].filter((ch) => !window.POPPINS_3D.glyphs[ch]);
      if (missing.length) throw new Error(`number() : caractère(s) absent(s) de la police 3D : ${missing.join(" ")}`);
      // Le chiffre est aligné à droite sur l'origine du groupe et l'unité part de là : le bloc reste centré sur la
      // valeur finale pendant le compte (la largeur du « 0 » de départ ne fait pas sauter la mise en page).
      const unitGeo = unit ? text(unit, size * (o.unitScale || 0.45)) : null;
      const gap = unit ? size * 0.12 : 0;
      const unitW = unitGeo ? unitGeo.boundingBox.max.x - unitGeo.boundingBox.min.x : 0;
      const cache = new Map();
      const geo = (str) => {
        if (!cache.has(str)) {
          const gm = text(str, size);
          gm.translate(-gm.boundingBox.max.x, 0, -depth / 2);
          gm.computeBoundingBox();
          cache.set(str, gm);
        }
        return cache.get(str);
      };
      const finalGeo = geo(final), finalW = finalGeo.boundingBox.max.x - finalGeo.boundingBox.min.x;
      const shift = (finalW - gap - unitW) / 2;  // centre le bloc chiffre + unité
      const group = new T.Group();
      group.name = `chiffre ${final}${unit ? ` ${unit}` : ""}`;
      const mesh = new T.Mesh(finalGeo, [front, side]);
      mesh.position.x = shift;
      group.add(mesh);
      if (unitGeo) {
        unitGeo.translate(-unitGeo.boundingBox.min.x, 0, -depth * (o.unitScale || 0.45) / 2);
        const um = new T.Mesh(unitGeo, [front, side]);
        um.position.x = shift + gap;
        group.add(um);
      }
      // Largeur bornée (maxW, en mètres) : un nombre long rétrécit au lieu de sortir du cadre.
      const fit = Math.min(1, (o.maxW || 2.0) / Math.max(finalW + gap + unitW, 1e-3));
      const it = this._add(group, Object.assign({y: 0.02}, o, {scale: (o.scale || 1) * fit}), (t, item) => {
        mesh.geometry = geo(fmt(from + (to - from) * E.out((t - item.at) / cd)));
      });
      // Contrôle des zones sur la valeur finale, pas sur le « 0 » du début du compte.
      mesh.geometry = finalGeo;
      group.updateMatrixWorld(true);
      it.finalBox = new T.Box3().setFromObject(group).applyMatrix4(group.matrixWorld.clone().invert());
      it.size = {w: (finalW + gap + unitW) * it.scale, h: size * 0.75 * it.scale};  // pour cadrer la caméra
      return it;
    }

    // Boîte produit / bloc avec étiquette sur la face avant.
    box(o = {}) {
      const w = o.w || 1.0, h = o.h || 1.4, d = o.d || 0.7;
      const g = new T.Group();
      g.name = o.label ? `boîte « ${o.label} »` : "boîte";
      const mesh = new T.Mesh(new T.RoundedBoxGeometry(w, h, d, 5, Math.min(w, d) * 0.06), this.gloss(o.color || "accent"));
      mesh.position.y = h / 2;
      g.add(mesh);
      if (o.label) {
        const face = canvasTexture(512, Math.round(512 * h / w));
        this.ui.text(face.ctx, o.label, 0.5, 0.56, {size: 0.16, align: "center", weight: 900, color: o.labelColor || "#ffffff"});
        if (o.sub) this.ui.text(face.ctx, o.sub, 0.5, 0.66, {size: 0.07, align: "center", color: o.labelColor || "#ffffff"});
        const p = new T.Mesh(new T.PlaneGeometry(w * 0.9, h * 0.9), new T.MeshBasicMaterial({map: face.tex, transparent: true}));
        p.position.set(0, h / 2, d / 2 + 0.002);
        g.add(p);
      }
      return this._add(g, o);
    }

    // Anneau lumineux posé au sol (bloom), qui se trace sur draw secondes.
    ring(o = {}) {
      const r = o.r || 1.2, tube = o.tube || 0.012, mat = this.glow(o.color || "accent", o.intensity || 4);
      const mesh = new T.Mesh(new T.TorusGeometry(r, tube, 12, 160, Math.PI * 2), mat);
      mesh.name = "anneau";
      mesh.rotation.x = -Math.PI / 2;
      const g = new T.Group();
      g.add(mesh);
      const drawDur = o.draw === undefined ? 1.2 : o.draw;
      return this._add(g, Object.assign({y: 0.01, enter: "none", shadow: false, bleed: true}, o), (t, it) => {
        const k = drawDur ? E.inOut((t - it.at) / drawDur) : 1;
        mesh.geometry.dispose();
        mesh.geometry = new T.TorusGeometry(r, tube, 12, 160, Math.max(0.001, Math.PI * 2 * k));
      });
    }

    // Trait de lumière le long de points 3D, tracé progressivement (parcours, progression).
    glowLine(points, o = {}) {
      const curve = new T.CatmullRomCurve3(points.map((p) => new T.Vector3(...p)));
      const geo = new T.TubeGeometry(curve, 200, o.width || 0.025, 8, false);
      const mesh = new T.Mesh(geo, this.glow(o.color || "accent", o.intensity || 4));
      mesh.name = "trait lumineux";
      const total = geo.index.count, drawDur = o.draw || 1.2;
      return this._add(mesh, Object.assign({enter: "none", shadow: false, bleed: true}, o), (t, it) => {
        geo.setDrawRange(0, Math.floor(total * E.inOut((t - it.at) / drawDur) / 6) * 6);
      });
    }

    // Icône du kit (lib/icons) sur une plaque : pastille 3D lisible.
    iconPlate(name, o = {}) {
      const size = o.size || 0.9;
      const g = new T.Group();
      g.name = `icône ${name}`;
      if (o.plate !== false) {
        const plate = new T.Mesh(new T.RoundedBoxGeometry(size, size, size * 0.12, 4, size * 0.18), this.gloss(o.plateColor || "#1b1b24"));
        g.add(plate);
      }
      const tex = canvasTexture(512, 512);
      const mat = new T.MeshBasicMaterial({map: tex.tex, transparent: true});
      const p = new T.Mesh(new T.PlaneGeometry(size * 0.78, size * 0.78), mat);
      p.position.z = size * 0.061;
      g.add(p);
      const img = new Image();
      this.pending.push(new Promise((resolve, reject) => {
        img.onload = () => { tex.ctx.drawImage(img, 0, 0, 512, 512); tex.tex.needsUpdate = true; resolve(); };
        img.onerror = () => reject(new Error(`icone inconnue : ${name} (liste : lib/icons/INDEX.txt)`));
      }));
      img.src = `lib/icons/${name}.svg`;
      return this._add(g, Object.assign({y: 1.2}, o));
    }

    // Colonnes 3D qui montent (comparaison de grandeurs), valeur au-dessus, libellé devant.
    columns(items, o = {}) {
      const g = new T.Group();
      g.name = "colonnes";
      // Par défaut, rangée ≤ 2,1 m et hauteur ≤ 1,3 m : tient dans la zone utile avec la caméra par défaut.
      const n = items.length, gap = o.gap ?? 0.22, bw = o.w || Math.min(0.6, (2.1 - (n - 1) * gap) / n), hmax = o.h || 1.3;
      const max = Math.max(...items.map((i) => +i.value)) || 1, total = n * bw + (n - 1) * gap;
      const bars = items.map((itm, i) => {
        const accent = !itm.color && i === n - 1;
        const mat = itm.color ? this.gloss(itm.color) : accent ? this.gloss("accent") : this.gloss("#1c1c24", {roughness: 0.18, clearcoat: 1});
        const mesh = new T.Mesh(new T.RoundedBoxGeometry(bw, 1, bw, 4, bw * 0.08), mat);
        mesh.position.x = -total / 2 + bw / 2 + i * (bw + gap);
        g.add(mesh);
        const val = this._sprite(itm.valueText || String(itm.value), {size: 0.3, color: i === n - 1 ? "accent" : "ink"});
        val.position.x = mesh.position.x;
        g.add(val);
        const lab = this._sprite(itm.label || "", {size: 0.22, color: "muted"});
        lab.position.set(mesh.position.x, -0.22, bw / 2 + 0.05);
        g.add(lab);
        return {mesh, val, h: hmax * (+itm.value / max), delay: i * (o.stagger || 0.3)};
      });
      return this._add(g, Object.assign({enter: "none", y: 0}, o), (t, it) => {
        for (const bb of bars) {
          const h = Math.max(0.001, bb.h * E.back((t - it.at - bb.delay) / 0.9));
          bb.mesh.scale.y = h;
          bb.mesh.position.y = h / 2;
          bb.val.position.y = h + 0.24;
          bb.val.material.opacity = clamp((t - it.at - bb.delay - 0.5) * 3);
        }
      });
    }

    // Texte en 3D (panneau toujours face caméra) : pour les étiquettes qui suivent un objet.
    label(text, o = {}) {
      const s = this._sprite(text, o);
      s.name = `« ${String(text).slice(0, 24)} »`;
      return this._add(s, Object.assign({y: 1.2, shadow: false}, o));
    }

    _sprite(text, o = {}) {
      const px = 160, ctx0 = document.createElement("canvas").getContext("2d");
      ctx0.font = this.ui.font(px, o.weight || 900);
      const tw = Math.ceil(ctx0.measureText(String(text)).width) + px;
      const {ctx, tex} = canvasTexture(tw, Math.round(px * 1.5));
      ctx.font = this.ui.font(px, o.weight || 900);
      ctx.fillStyle = this.ui.color(o.color || "ink");
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(text), tw / 2, px * 0.78);
      // depthWrite : sans profondeur, la passe de profondeur de champ voit le fond derrière et floute l'étiquette.
      const mat = new T.SpriteMaterial({map: tex, transparent: true, depthWrite: true, alphaTest: 0.05});
      const sp = new T.Sprite(mat);
      const size = o.size || 0.4;
      sp.scale.set(size * tw / (px * 1.5) * 1.5, size * 1.5, 1);
      return sp;
    }

    // Poussière lumineuse (profondeur et bloom), déterministe.
    particles(o = {}) {
      const n = o.count || 90, rand = rng(o.seed || 7), pos = new Float32Array(n * 3), base = [];
      for (let i = 0; i < n; i++) base.push([(rand() - 0.5) * 9, rand() * 4.5, (rand() - 0.5) * 6 - 1, rand() * 6.28]);
      const geo = new T.BufferGeometry();
      geo.setAttribute("position", new T.BufferAttribute(pos, 3));
      const dot = canvasTexture(64, 64), gr = dot.ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
      gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(0.4, "rgba(255,255,255,0.6)"); gr.addColorStop(1, "rgba(255,255,255,0)");
      dot.ctx.fillStyle = gr; dot.ctx.fillRect(0, 0, 64, 64);
      const mat = new T.PointsMaterial({color: this.color(o.color || "accent"), map: dot.tex, size: o.size || 0.05, transparent: true,
        opacity: 0.55, depthWrite: false, blending: T.AdditiveBlending});
      const pts = new T.Points(geo, mat);
      pts.name = "particules";
      return this._add(pts, Object.assign({enter: "none", shadow: false, bleed: true}, o), (t) => {
        base.forEach((b, i) => {
          pos[i * 3] = b[0] + Math.sin(t * 0.3 + b[3]) * 0.15;
          pos[i * 3 + 1] = b[1] + ((t * 0.12 + b[3]) % 1) * 0.4;
          pos[i * 3 + 2] = b[2];
        });
        geo.attributes.position.needsUpdate = true;
      });
    }

    // Objet libre : fn(T, scene3d) renvoie un Object3D (+ éventuellement update(tLocal, t) via o.update).
    custom(fn, o = {}) {
      const obj = fn(T, this);
      return this._add(obj, o, o.update ? (t, it) => o.update(t - it.at, t, obj) : null);
    }

    // ── caméra ──
    // Mouvement vers {pos, target, fov} depuis l'état courant.
    camera(o = {}) { this.moves.push(Object.assign({at: 0, dur: 1.5, ease: "inOut"}, o)); return this; }
    // Orbite autour de target : angles en degrés (0 = face), rayon et hauteur en mètres.
    orbit(o = {}) {
      const target = o.target || this.start.target, radius = o.radius || 9.5, height = o.height === undefined ? 1.5 : o.height;
      const a0 = (o.from || 0) * Math.PI / 180, a1 = (o.to === undefined ? 30 : o.to) * Math.PI / 180;
      const h1 = o.toHeight === undefined ? height : o.toHeight, r1 = o.toRadius || radius;
      return this.camera(Object.assign({}, o, {path: (k) => {
        const a = lerp(a0, a1, k), r = lerp(radius, r1, k);
        return {pos: [target[0] + Math.sin(a) * r, lerp(height, h1, k), target[2] + Math.cos(a) * r], target};
      }}));
    }
    // Poussée vers l'objet (de distance from à to, en mètres).
    push(o = {}) {
      const target = o.target || this.start.target, from = o.from || 9.5, to = o.to || 6.5;
      return this.camera(Object.assign({}, o, {path: (k) => ({pos: [target[0], target[1] + 0.25, target[2] + lerp(from, to, k)], target})}));
    }
    shake(o = {}) { this.shakes.push(Object.assign({at: 0, dur: 0.35, amp: 0.05}, o)); return this; }

    _camState(t) {
      let st = {pos: this.start.pos.slice(), target: this.start.target.slice(), fov: this.start.fov};
      for (const m of this.moves.slice().sort((a, b) => a.at - b.at)) {
        if (t < m.at) continue;
        const k = (EASES[m.ease] || E.inOut)((t - m.at) / m.dur);
        const end = m.path ? m.path(k) : m;
        const mix = m.path ? 1 : k;
        st = {
          pos: end.pos ? st.pos.map((v, i) => lerp(v, end.pos[i], mix)) : st.pos,
          target: end.target ? st.target.map((v, i) => lerp(v, end.target[i], mix)) : st.target,
          fov: end.fov !== undefined ? lerp(st.fov, end.fov, m.path ? k : mix) : st.fov,
        };
      }
      for (const s of this.shakes) {
        if (t >= s.at && t < s.at + s.dur) {
          const d = 1 - (t - s.at) / s.dur;
          st.pos[0] += Math.sin(t * 91) * s.amp * d; st.pos[1] += Math.cos(t * 77) * s.amp * d;
        }
      }
      return st;
    }

    // ── rendu ──
    async render(t) {
      this.lastT = t;
      if (this.pending.length) { await Promise.all(this.pending); this.pending = []; }
      if (!this.fontsReady) {
        await Promise.all([900, 800, 600].map((w) => document.fonts.load(`${w} 64px Studio`)));
        this.fontsReady = true;
      }
      for (const it of this.items) {
        const k = this._apply(it, t);
        if (k >= 0 && it.update) it.update(t, it);
      }
      const st = this._camState(t);
      this.cam.position.set(...st.pos);
      this.cam.lookAt(new T.Vector3(...st.target));
      if (this.cam.fov !== st.fov) { this.cam.fov = st.fov; }
      this.cam.updateProjectionMatrix();
      if (this.mirror) {
        const u = this.mirror.material.uniforms;
        u.uCam.value.set(this.cam.position.x, this.cam.position.z);
        u.uTarget.value.set(st.target[0], st.target[2]);
      }
      this.post.final.uniforms.focus.value = this.cam.position.distanceTo(new T.Vector3(...(this.focus ? this.focus(t) : st.target)));
      this.post.render(this.scene, this.cam, t);
      this.renderer.getContext().finish();  // image complète avant la capture
    }

    // Contrôle des zones : boîtes englobantes projetées à l'écran (mêmes règles que studio.js).
    check() {
      const out = [], box = new T.Box3(), v = new T.Vector3();
      let covered = 0;
      const ux0 = 60, ux1 = 960, uy0 = 170, uy1 = 1180;
      for (const it of this.items) {
        if (!it.obj.visible || it.bleed) continue;
        if (it.finalBox) { it.obj.updateMatrixWorld(); box.copy(it.finalBox).applyMatrix4(it.obj.matrixWorld); }
        else box.setFromObject(it.obj);
        if (box.isEmpty()) continue;
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (let i = 0; i < 8; i++) {
          v.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).project(this.cam);
          const px = (v.x + 1) / 2 * W, py = (1 - v.y) / 2 * H;
          x0 = Math.min(x0, px); x1 = Math.max(x1, px); y0 = Math.min(y0, py); y1 = Math.max(y1, py);
        }
        const pb = [];
        if (y1 > 1205) pb.push(`descend à y ${Math.round(y1)} (sous-titres dès 1220)`);
        if (x1 > 970) pb.push(`déborde à droite x ${Math.round(x1)} (icônes TikTok après 960)`);
        if (x0 < 35) pb.push(`colle au bord gauche x ${Math.round(x0)}`);
        // Bande du titre 2D (y < 430) : un objet 3D qui y monte passe sous le mot-clé (titleBand: false si pas de titre).
        const top = this.o.titleBand === false ? 130 : 430;
        if (y0 < top) pb.push(top > 130 ? `monte sous le titre (y ${Math.round(y0)} < ${top})` : `monte à y ${Math.round(y0)}`);
        if (pb.length) out.push(`3D ${it.label} ${pb.join(", ")}`);
        covered += Math.max(0, Math.min(x1, ux1) - Math.max(x0, ux0)) * Math.max(0, Math.min(y1, uy1) - Math.max(y0, uy0));
      }
      const ratio = covered / ((ux1 - ux0) * (uy1 - uy0));
      // Image vide à la coupe : à t = 0, au moins un objet doit être déjà là (enter « none » ou at > 0 pour les autres).
      if (this.lastT === 0 && this.items.some((it) => !it.bleed)
          && !this.items.some((it) => !it.bleed && it.at <= 0 && it.enter === "none")) {
        out.push("image vide à la coupe : le sujet doit être visible à t = 0 (at: 0, enter: \"none\")");
      }
      // Seuil plus bas que le kit 2D : un objet 3D plein (chiffre, téléphone) remplit moins sa boîte qu'une icône.
      if (this.items.some((it) => !it.bleed) && ratio < 0.07) out.push(`scène 3D vide : les objets couvrent ~${Math.round(ratio * 100)} % de la zone utile (rapprocher la caméra : push, orbit radius)`);
      return out;
    }
  }

  function strip(k) { const o = Object.assign({}, k); delete o.t; return o; }

  window.Studio3D = {scene: (o) => new Scene3D(o), THREE: T};
})();

// NBA 历史前十 · 画风核心：夜场球馆平面插画——深胡桃木、暖色顶光（分层平涂，不做渐变底），奶油色细描线，纸面颗粒。
// 只用总纲色板 6 色（加减明暗、透明度）。所有随机都用种子，同一时刻渲两次逐像素一致。
(() => {
const W = 1920, H = 1080, TAU = Math.PI * 2;
const { clamp, lerp } = U;
const C = { bg: '#16110D', surf: '#8A5A33', ink: '#F2E7D3', sub: '#A08C74', acc: '#E2582B', gold: '#E6B53F' };
const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const mix = (a, b, k) => { const A = hex(a), B = hex(b); return '#' + A.map((v, i) => Math.round(lerp(v, B[i], k)).toString(16).padStart(2, '0')).join(''); };
const dk = (a, k) => mix(a, '#000000', k), lt = (a, k) => mix(a, '#ffffff', k);
const rgba = (h, a) => { const [r, g, b] = hex(h); return `rgba(${r},${g},${b},${a})`; };
// 派生色（都是 6 色的明暗）
const D = {
  wall: mix(C.bg, C.surf, 0.2), wall2: mix(C.bg, C.surf, 0.28), floor: C.surf, floorD: dk(C.surf, 0.22), floorL: mix(C.surf, C.gold, 0.18),
  walnut: mix(C.bg, C.surf, 0.46), walnutD: mix(C.bg, C.surf, 0.32), walnutL: mix(C.bg, C.surf, 0.6),
  skin: mix(C.surf, C.ink, 0.42), skinD: mix(C.surf, C.ink, 0.22), cuff: mix(C.bg, C.sub, 0.25),
  brass: mix(C.gold, C.surf, 0.3), brassD: mix(C.gold, C.bg, 0.45), velvet: mix(C.bg, C.acc, 0.22),
};
const F = (px, f = 'Anton-400') => `${px}px "${f}"`;
const ZH = (px, w = 'Heavy') => `${px}px "PuHui-${w}"`;
const ease = MO;

// ---------- 小工具 ----------
const rr = (c, x, y, w, h, r) => { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); };
const ell = (c, x, y, rx, ry, rot = 0) => { c.beginPath(); c.ellipse(x, y, Math.max(0.1, rx), Math.max(0.1, ry), rot, 0, TAU); };
const text = (c, s, x, y, font, col, align = 'center', base = 'alphabetic', spacing = 0) => {
  c.save(); c.font = font; c.fillStyle = col; c.textAlign = align; c.textBaseline = base; if (spacing) c.letterSpacing = spacing + 'px'; c.fillText(s, x, y); c.restore(); };
// 12fps 步进（纸片、手、字的「一拍二」），相机仍然平滑
const st = s => MO.step(s, 12);
const pop = (s, at, dur = 0.35) => MO.backOut ? MO.backOut(clamp((s - at) / dur)) : MO.cubicOut(clamp((s - at) / dur));
const inn = (s, at, dur = 0.5, e = MO.cubicOut) => e(clamp((s - at) / dur));

// ---------- 纸面颗粒（预生成，按 1/12 秒换一张，不闪烁太快） ----------
const grains = [];
const grain = k => { if (!grains[k]) { const g = document.createElement('canvas'); g.width = 480; g.height = 270; const x = g.getContext('2d'), im = x.createImageData(480, 270), r = U.rng(1000 + k);
    for (let i = 0; i < im.data.length; i += 4) { const v = r() * 255; im.data[i] = im.data[i + 1] = im.data[i + 2] = v; im.data[i + 3] = 22; }
    x.putImageData(im, 0, 0); grains[k] = g; } return grains[k]; };
// 整体曝光：分层平涂的暗部太闷（全片平均亮度只有 47/255），统一提一档再上颗粒和暗角
let _tmp = null;
const expose = (c) => { if (!_tmp) { _tmp = document.createElement('canvas'); _tmp.width = W; _tmp.height = H; }
  const g = _tmp.getContext('2d'); g.clearRect(0, 0, W, H); g.drawImage(c.canvas, 0, 0);
  c.save(); c.setTransform(1, 0, 0, 1, 0, 0); c.filter = 'brightness(1.55) contrast(1.06)'; c.drawImage(_tmp, 0, 0); c.restore(); };
const finish = (c, t) => {
  expose(c);
  c.save(); c.globalCompositeOperation = 'overlay'; c.imageSmoothingEnabled = true; c.drawImage(grain(Math.floor(t * 12) % 6), 0, 0, W, H); c.restore();
  // 分层暗角：三圈平涂，不用渐变
  c.save(); c.fillStyle = rgba(C.bg, 0.14); c.beginPath(); c.rect(0, 0, W, H); ell(c, W / 2, H / 2, W * 0.62, H * 0.66); c.fill('evenodd');
  c.fillStyle = rgba(C.bg, 0.14); c.beginPath(); c.rect(0, 0, W, H); ell(c, W / 2, H / 2, W * 0.72, H * 0.8); c.fill('evenodd'); c.restore();
};

// ---------- 顶光：分层平涂的光池 ----------
const pool = (c, x, y, rx, ry, a = 0.07, n = 4, col = C.gold) => { c.save(); for (let i = 0; i < n; i++) { c.fillStyle = rgba(col, a); ell(c, x, y, rx * (1 - i * 0.2), ry * (1 - i * 0.2)); c.fill(); } c.restore(); };
const beam = (c, x, top, w0, w1, bottom, a = 0.05) => { c.save(); for (let i = 0; i < 3; i++) { const k = 1 - i * 0.28; c.fillStyle = rgba(C.gold, a);
  c.beginPath(); c.moveTo(x - w0 * k, top); c.lineTo(x + w0 * k, top); c.lineTo(x + w1 * k, bottom); c.lineTo(x - w1 * k, bottom); c.closePath(); c.fill(); } c.restore(); };

// ---------- 木地板（俯视/正视两种） ----------
const planksFlat = (c, x0, y0, w, h, seed = 1, col = D.floor, pw = 46) => P_cached('pf' + [w, h, seed, col, pw].join('_'), w, h, g => {
  g.fillStyle = col; g.fillRect(0, 0, w, h); const r = U.rng(seed);
  for (let x = 0; x < w; x += pw) { let y = -r() * 300; while (y < h) { const L = 220 + r() * 380, k = r();
      g.fillStyle = k < 0.33 ? rgba(C.bg, 0.07) : k < 0.66 ? rgba(C.gold, 0.06) : 'rgba(0,0,0,0)'; g.fillRect(x, y, pw, L);
      g.fillStyle = rgba(C.bg, 0.28); g.fillRect(x, y, pw, 2); y += L; }
    g.fillStyle = rgba(C.bg, 0.3); g.fillRect(x, 0, 2, h); }
}, x0, y0, c);
function P_cached(key, w, h, fn, x, y, c) { const im = PAINT.cached('nba_' + key, w, h, fn); c.drawImage(im, x, y); return im; }
// 透视地板：地平线 hy，灭点 vx；返回把地面坐标 (u 横向 -1..1 倍屏宽, v 0..1 深度) 投到屏幕的函数
const persp = (hy, vx = W / 2, bottom = H, spread = 2.4) => (u, v) => { const yy = lerp(bottom, hy, v); const s = (yy - hy) / (bottom - hy); return [vx + u * W * spread * s / 2, yy]; };
const floorPersp = (c, hy, opt = {}) => {
  const vx = opt.vx ?? W / 2, pr = persp(hy, vx, H + 200, opt.spread || 2.6);
  c.save(); c.fillStyle = D.floor; c.fillRect(-400, hy, W + 800, H - hy + 400);
  // 木板缝：朝灭点收拢
  for (let i = -40; i <= 40; i++) { const u = i / 20; const [x0, y0] = pr(u, 0), [x1, y1] = pr(u, 1); c.strokeStyle = rgba(C.bg, 0.26); c.lineWidth = 1.5; c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.stroke();
    if (i % 3 === 0) { c.fillStyle = rgba(C.gold, 0.05); const [x2] = pr(u + 0.05, 0), [x3] = pr(u + 0.05, 1); c.beginPath(); c.moveTo(x0, y0); c.lineTo(x2, y0); c.lineTo(x3, y1); c.lineTo(x1, y1); c.fill(); } }
  // 横向接缝（越远越密）
  const r = U.rng(7); for (let k = 1; k < 26; k++) { const v = 1 - Math.pow(1 - k / 26, 1.8); const [, y] = pr(0, v); c.fillStyle = rgba(C.bg, 0.12 + r() * 0.08); c.fillRect(-400, y, W + 800, 1.5); }
  // 场地线（中线、中圈）
  if (opt.lines !== false) { c.strokeStyle = rgba(C.ink, 0.75); c.lineWidth = 5;
    const cy = opt.centerV ?? 0.35; const [cx, yC] = pr(0, cy); const [, yA] = pr(0, cy - 0.12), [, yB] = pr(0, cy + 0.12); const [xR] = pr(0.28, cy);
    c.beginPath(); c.ellipse(cx, yC, (xR - cx), (yA - yB) / 2, 0, 0, TAU); c.stroke();
    c.beginPath(); c.moveTo(-400, yC); c.lineTo(W + 400, yC); c.stroke(); }
  c.restore(); return pr;
};
// 看台：几排暗色座位带＋上方吊着的退役球衣（远景、低对比）
const stands = (c, hy, opt = {}) => {
  c.save(); c.fillStyle = C.bg; c.fillRect(-400, -400, W + 800, hy + 400);
  const r = U.rng(opt.seed || 3);
  for (let row = 0; row < 9; row++) { const y = hy - 30 - row * 34; c.fillStyle = row % 2 ? D.wall : D.wall2; c.fillRect(-400, y - 26, W + 800, 26);
    for (let x = -400 + (row % 2) * 14; x < W + 400; x += 28) { if (r() < 0.86) { c.fillStyle = rgba(C.bg, 0.55); c.fillRect(x, y - 22, 20, 18); } } }
  // 记分台挡板
  c.fillStyle = D.walnutD; c.fillRect(-400, hy - 26, W + 800, 26); c.fillStyle = rgba(C.gold, 0.35); c.fillRect(-400, hy - 26, W + 800, 3);
  // 退役球衣横幅
  (opt.banners || []).forEach((b, i, a) => { const x = W / 2 + (i - (a.length - 1) / 2) * 150, y = 70 + (i % 2) * 18; const sw = Math.sin((opt.t || 0) * 0.8 + i) * 2;
    c.save(); c.translate(x, y); c.rotate(sw * 0.004); c.fillStyle = rgba(C.ink, 0.5); c.fillRect(-1, -80, 2, 80); jersey(c, 0, 60, 0.36, b, { t: 0, flat: true, dim: 0.45 }); c.restore(); });
  c.restore();
};

// ---------- 篮球 ----------
const ball = (c, x, y, r, rot = 0, opt = {}) => {
  c.save(); if (opt.shadow !== false) { c.fillStyle = rgba(C.bg, 0.4); ell(c, x + r * 0.15, (opt.floorY ?? y + r) - 2, r * 1.05, r * 0.22); c.fill(); }
  c.translate(x, y); c.fillStyle = opt.col || C.acc; ell(c, 0, 0, r, r); c.fill();
  c.save(); c.beginPath(); c.arc(0, 0, r, 0, TAU); c.clip();
  c.fillStyle = dk(opt.col || C.acc, 0.28); ell(c, r * 0.45, r * 0.4, r * 1.05, r * 1.05); c.fill();   // 背光面
  c.fillStyle = dk(opt.col || C.acc, 0.12); ell(c, -r * 0.1, -r * 0.1, r * 0.98, r * 0.98); c.globalCompositeOperation = 'source-over';
  c.rotate(rot); c.strokeStyle = dk(C.bg, 0.1); c.lineWidth = Math.max(1.2, r * 0.06); c.lineCap = 'round';
  c.beginPath(); c.moveTo(-r, 0); c.lineTo(r, 0); c.stroke(); c.beginPath(); c.moveTo(0, -r); c.lineTo(0, r); c.stroke();
  c.beginPath(); c.ellipse(-r * 0.95, 0, r * 0.55, r * 1.05, 0, -Math.PI / 2, Math.PI / 2); c.stroke();
  c.beginPath(); c.ellipse(r * 0.95, 0, r * 0.55, r * 1.05, 0, Math.PI / 2, Math.PI * 1.5); c.stroke();
  c.restore();
  c.strokeStyle = rgba(C.ink, 0.5); c.lineWidth = Math.max(1, r * 0.06); c.beginPath(); c.arc(0, 0, r * 0.78, Math.PI * 1.1, Math.PI * 1.45); c.stroke();
  c.restore();
};

// ---------- 球衣（背面）：who = {name, num, col, trim, numCol} ----------
const jersey = (c, x, y, s, j, opt = {}) => {
  const t = opt.t || 0, sway = opt.flat ? 0 : Math.sin(t * 1.3 + (opt.ph || 0)) * 0.02;
  c.save(); c.translate(x, y); c.scale(s, s); c.rotate(sway);
  const body = j.col, trim = j.trim || C.ink;
  const path = () => { c.beginPath(); c.moveTo(-95, -160); c.quadraticCurveTo(-60, -150, -48, -175); c.lineTo(48, -175); c.quadraticCurveTo(60, -150, 95, -160);
    c.quadraticCurveTo(108, -90, 150, -55); c.lineTo(150, 180); c.quadraticCurveTo(0, 196, -150, 180); c.lineTo(-150, -55); c.quadraticCurveTo(-108, -90, -95, -160); c.closePath(); };
  if (!opt.flat) { c.save(); c.translate(10, 14); c.fillStyle = rgba(C.bg, 0.45); path(); c.fill(); c.restore(); }
  c.fillStyle = body; path(); c.fill();
  // 领口与袖口滚边
  c.strokeStyle = trim; c.lineWidth = 10; c.beginPath(); c.moveTo(-48, -175); c.quadraticCurveTo(0, -150, 48, -175); c.stroke();
  c.beginPath(); c.moveTo(-95, -160); c.quadraticCurveTo(-108, -90, -150, -55); c.stroke(); c.beginPath(); c.moveTo(95, -160); c.quadraticCurveTo(108, -90, 150, -55); c.stroke();
  // 布料明暗：两片平涂
  c.save(); path(); c.clip(); c.fillStyle = rgba(C.bg, 0.16); c.beginPath(); c.moveTo(40, -200); c.quadraticCurveTo(70 + sway * 800, 20, 30, 210); c.lineTo(200, 210); c.lineTo(200, -200); c.fill();
  c.fillStyle = rgba(C.ink, 0.06); c.fillRect(-150, -60, 60, 260); c.restore();
  if (j.name) { c.save(); c.font = F(44); c.fillStyle = j.numCol || trim; c.textAlign = 'center'; c.letterSpacing = '4px';
    const name = j.name, n = name.length, sp = Math.min(30, 220 / Math.max(1, n)); // 弧形字
    for (let i = 0; i < n; i++) { const a = (i - (n - 1) / 2) * sp / 230; c.save(); c.translate(Math.sin(a) * 230, -60 - Math.cos(a) * 230 + 230 - 10); c.rotate(a); c.fillText(name[i], 0, 0); c.restore(); }
    c.restore(); }
  if (j.num != null) { c.save(); c.font = F(170); c.textAlign = 'center'; c.textBaseline = 'alphabetic'; c.lineJoin = 'round';
    c.strokeStyle = j.numStroke || trim; c.lineWidth = 12; c.strokeText(String(j.num), 0, 130); c.fillStyle = j.numCol || C.ink; c.fillText(String(j.num), 0, 130); c.restore(); }
  if (opt.dim) { c.globalAlpha = opt.dim; c.fillStyle = C.bg; path(); c.fill(); }
  c.restore();
};
// 衣架
const hanger = (c, x, y, s = 1) => { c.save(); c.translate(x, y); c.scale(s, s); c.strokeStyle = D.brass; c.lineWidth = 6; c.lineCap = 'round';
  c.beginPath(); c.arc(0, -205, 16, Math.PI, Math.PI * 2.3); c.stroke(); c.beginPath(); c.moveTo(0, -190); c.lineTo(-120, -150); c.lineTo(120, -150); c.closePath(); c.stroke(); c.restore(); };

// ---------- 手（只出手）：pose 'grip' 握、'open' 张开、'point' 指、'pinch' 捏 ----------
const hand = (c, x, y, s, rot, pose = 'grip', opt = {}) => {
  c.save(); c.translate(x, y); c.rotate(rot); c.scale(s * (opt.flip ? -1 : 1), s);
  // 袖口（从画面外伸进来）
  c.fillStyle = D.cuff; rr(c, -46, 60, 92, 420, 26); c.fill(); c.fillStyle = rgba(C.ink, 0.12); c.fillRect(-46, 70, 92, 8);
  c.fillStyle = D.skin; rr(c, -42, -30, 84, 110, 34); c.fill();                     // 手掌
  const fing = (dx, len, ang, w = 19) => { c.save(); c.translate(dx, -22); c.rotate(ang); rr(c, -w / 2, -len, w, len + 12, w / 2); c.fill(); c.restore(); };
  if (pose === 'open') { fing(-28, 70, -0.18); fing(-9, 84, -0.05); fing(10, 80, 0.06); fing(28, 64, 0.2); }
  else if (pose === 'point') { fing(-9, 92, 0); c.fillStyle = D.skinD; rr(c, -42, -36, 84, 30, 14); c.fill(); }
  else if (pose === 'pinch') { fing(-6, 60, 0.15); c.fillStyle = D.skinD; rr(c, -40, -34, 80, 26, 12); c.fill(); }
  else { c.fillStyle = D.skinD; rr(c, -42, -50, 84, 40, 18); c.fill(); c.fillStyle = D.skin; for (let i = 0; i < 4; i++) { rr(c, -40 + i * 21, -58, 18, 26, 9); c.fill(); } }
  c.fillStyle = D.skin; c.save(); c.translate(40, 20); c.rotate(pose === 'open' ? 0.9 : 0.4); rr(c, -11, -50, 22, 56, 11); c.fill(); c.restore();   // 拇指
  c.restore();
};

// ---------- 戒指 ----------
const ring = (c, x, y, s, opt = {}) => {
  c.save(); c.translate(x, y); c.scale(s, s);
  c.fillStyle = rgba(C.bg, 0.35); ell(c, 6, 64, 62, 14); c.fill();
  c.strokeStyle = D.brassD; c.lineWidth = 24; ell(c, 0, 18, 48, 40); c.stroke();
  c.strokeStyle = C.gold; c.lineWidth = 16; ell(c, 0, 16, 48, 40); c.stroke();
  c.fillStyle = D.brassD; rr(c, -46, -52, 92, 58, 14); c.fill(); c.fillStyle = C.gold; rr(c, -42, -56, 84, 52, 12); c.fill();
  c.fillStyle = opt.gem || C.acc; ell(c, 0, -30, 22, 16); c.fill(); c.fillStyle = rgba(C.ink, 0.6); ell(c, -6, -34, 6, 4); c.fill();
  if (opt.year) text(c, String(opt.year), 0, 104, F(30, 'RobotoCondensed'), C.ink);
  c.restore();
};
// ---------- 奖杯：kind 'title' 金杯（球在网上）、'mvp' 立柱奖杯、'fmvp' 小金杯、'medal' 奖牌、'dpoy' 盾 ----------
const trophy = (c, x, y, s, kind = 'title') => {
  c.save(); c.translate(x, y); c.scale(s, s); c.fillStyle = rgba(C.bg, 0.4); ell(c, 0, 4, 70, 12); c.fill();
  if (kind === 'title') {
    c.fillStyle = D.walnutD; rr(c, -46, -40, 92, 40, 6); c.fill();
    c.fillStyle = D.brassD; c.beginPath(); c.moveTo(-26, -40); c.lineTo(26, -40); c.lineTo(14, -170); c.lineTo(-14, -170); c.fill();
    c.fillStyle = C.gold; c.beginPath(); c.moveTo(-22, -40); c.lineTo(18, -40); c.lineTo(8, -170); c.lineTo(-12, -170); c.fill();
    c.fillStyle = C.gold; c.beginPath(); c.moveTo(-34, -170); c.lineTo(34, -170); c.lineTo(22, -228); c.lineTo(-22, -228); c.fill();
    c.strokeStyle = D.brassD; c.lineWidth = 2; for (let i = -2; i <= 2; i++) { c.beginPath(); c.moveTo(i * 13, -170); c.lineTo(i * 8.5, -228); c.stroke(); }
    c.beginPath(); c.moveTo(-28, -199); c.lineTo(28, -199); c.stroke();
    ball(c, 0, -262, 34, 0.4, { col: C.gold, shadow: false });
  } else if (kind === 'mvp' || kind === 'fmvp') {
    const g = kind === 'mvp' ? D.brass : C.gold, h = kind === 'mvp' ? 230 : 190;
    c.fillStyle = D.walnutD; rr(c, -44, -44, 88, 44, 6); c.fill();
    c.fillStyle = dk(g, 0.25); c.fillRect(-20, -h, 40, h - 44); c.fillStyle = g; c.fillRect(-16, -h, 30, h - 44);
    ball(c, 0, -h - 26, 28, 1, { col: g, shadow: false });
  } else if (kind === 'medal') {
    c.fillStyle = C.acc; c.beginPath(); c.moveTo(-30, -190); c.lineTo(-6, -90); c.lineTo(6, -90); c.lineTo(30, -190); c.lineTo(14, -190); c.lineTo(0, -120); c.lineTo(-14, -190); c.fill();
    c.fillStyle = D.brassD; ell(c, 0, -60, 50, 50); c.fill(); c.fillStyle = C.gold; ell(c, -2, -62, 44, 44); c.fill(); c.fillStyle = rgba(C.ink, 0.35); ell(c, -2, -62, 26, 26); c.fill();
  } else if (kind === 'dpoy') {
    c.fillStyle = D.walnutD; rr(c, -44, -44, 88, 44, 6); c.fill();
    c.fillStyle = dk(C.ink, 0.25); c.beginPath(); c.moveTo(-50, -200); c.lineTo(50, -200); c.lineTo(46, -110); c.quadraticCurveTo(0, -50, -46, -110); c.closePath(); c.fill();
    c.fillStyle = C.ink; c.beginPath(); c.moveTo(-42, -192); c.lineTo(42, -192); c.lineTo(38, -114); c.quadraticCurveTo(0, -62, -38, -114); c.closePath(); c.fill();
    ball(c, 0, -140, 22, 0.3, { shadow: false });
  }
  c.restore();
};

// ---------- 翻牌数字（记分板）：在 at 时刻从 from 翻到 to，低位先翻 ----------
const flipDigits = (c, x, y, str, s, at, opt = {}) => {
  const cw = opt.cw || 92, ch = opt.ch || 150, gap = 10, n = str.length, tot = n * cw + (n - 1) * gap;
  let x0 = x - tot / 2; c.save();
  for (let i = 0; i < n; i++) {
    const chr = str[i], isSep = chr === '.' || chr === ',' || chr === ':' || chr === '·';
    const pi = clamp((s - at - (n - 1 - i) * 0.07) / 0.32), w = isSep ? cw * 0.4 : cw;
    if (!isSep) { c.fillStyle = D.walnutD; rr(c, x0, y - ch / 2, w, ch, 10); c.fill(); c.fillStyle = rgba(C.bg, 0.5); c.fillRect(x0, y - 2, w, 4); }
    const show = pi >= 1 ? chr : (opt.from ? (opt.from[i] || ' ') : ' ');
    if (pi > 0 && pi < 1 && !isSep) { // 上半片翻下
      const k = Math.cos(pi * Math.PI); c.save(); c.translate(x0 + w / 2, y); c.scale(1, Math.abs(k)); c.fillStyle = D.walnutL; rr(c, -w / 2, k > 0 ? -ch / 2 : 0, w, ch / 2, 8); c.fill(); c.restore();
      text(c, pi < 0.5 ? show : chr, x0 + w / 2, y + ch * 0.33, F(ch * 0.86, opt.font || 'Anton-400'), opt.col || C.ink);
    } else text(c, show, x0 + w / 2, y + ch * 0.33, F(ch * 0.86, opt.font || 'Anton-400'), opt.col || C.ink);
    x0 += w + gap;
  }
  c.restore();
};

// ---------- 吊牌标签（贴在物上的字）：黑底奶油字，带细绳 ----------
const tag = (c, x, y, s, str, opt = {}) => { c.save(); c.translate(x, y); c.rotate(opt.rot || 0); c.font = opt.font || ZH(34); const w = c.measureText(str).width + 40;
  if (opt.string !== false) { c.strokeStyle = rgba(C.ink, 0.5); c.lineWidth = 2; c.beginPath(); c.moveTo(0, -60); c.lineTo(0, -24); c.stroke(); }
  c.fillStyle = opt.bg || C.bg; rr(c, -w / 2, -24, w, 56, 6); c.fill(); c.strokeStyle = rgba(opt.line || C.gold, 0.8); c.lineWidth = 2; rr(c, -w / 2 + 5, -19, w - 10, 46, 4); c.stroke();
  text(c, str, 0, 15, opt.font || ZH(34), opt.col || C.ink); c.restore(); };
// 黄铜铭牌（刻字逐字出现）
const plate = (c, x, y, w, h, str, p = 1, opt = {}) => { c.save(); c.fillStyle = D.brassD; rr(c, x - w / 2, y - h / 2, w, h, 6); c.fill(); c.fillStyle = D.brass; rr(c, x - w / 2 + 3, y - h / 2 + 3, w - 6, h - 6, 5); c.fill();
  [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([a, b]) => { c.fillStyle = D.brassD; ell(c, x + a * (w / 2 - 10), y + b * (h / 2 - 9), 3.5, 3.5); c.fill(); });
  const n = Math.round(str.length * clamp(p)); text(c, str.slice(0, n), x, y + h * 0.27, opt.font || F(h * 0.62), opt.col || C.bg); c.restore(); };

window.NB = { W, H, TAU, C, D, mix, dk, lt, rgba, F, ZH, rr, ell, text, st, pop, inn, finish, pool, beam, planksFlat, persp, floorPersp, stands, ball, jersey, hanger, hand, ring, trophy, flipDigits, tag, plate };
})();

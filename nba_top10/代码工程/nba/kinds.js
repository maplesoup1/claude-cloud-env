// 镜头种类：每种是 (c, s, p, d) → 画一个世界（1920×1080 世界坐标），s = 本镜局部秒，d = 镜长。相机在 player.js 里统一算。
(() => {
const N = NB, { W, H, TAU, C, D, rgba, F, ZH, rr, ell, text, st, inn, pop } = N;
const { clamp, lerp } = U;
const K = window.NBK = {};
// 球员资料：球衣配色只用色板里的色
const J = {
  curry:   { name: 'CURRY', num: 30, col: N.mix(C.ink, C.gold, 0.15), trim: C.gold, numCol: C.gold, numStroke: N.dk(C.gold, 0.5) },
  kobe:    { name: 'BRYANT', num: 24, col: C.gold, trim: C.bg, numCol: C.ink, numStroke: C.bg },
  hakeem:  { name: 'OLAJUWON', num: 34, col: C.acc, trim: C.ink, numCol: C.ink, numStroke: N.dk(C.acc, 0.5) },
  jokic:   { name: 'JOKIC', num: 15, col: N.mix(C.bg, C.sub, 0.35), trim: C.gold, numCol: C.gold, numStroke: C.bg },
  shaq:    { name: "O'NEAL", num: 34, col: C.gold, trim: N.dk(C.acc, 0.3), numCol: C.ink, numStroke: N.dk(C.acc, 0.35) },
  duncan:  { name: 'DUNCAN', num: 21, col: N.mix(C.bg, C.sub, 0.18), trim: C.ink, numCol: C.ink, numStroke: C.bg },
  wilt:    { name: 'CHAMBERLAIN', num: 13, col: C.ink, trim: C.acc, numCol: C.acc, numStroke: N.dk(C.acc, 0.5) },
  russell: { name: 'RUSSELL', num: 6, col: C.ink, trim: N.mix(C.sub, C.bg, 0.4), numCol: N.mix(C.sub, C.bg, 0.45), numStroke: C.ink },
  bird:    { name: 'BIRD', num: 33, col: C.ink, trim: N.mix(C.sub, C.bg, 0.4), numCol: N.mix(C.sub, C.bg, 0.45), numStroke: C.ink },
  magic:   { name: 'JOHNSON', num: 32, col: C.gold, trim: C.bg, numCol: C.ink, numStroke: C.bg },
  kareem:  { name: 'ABDUL-JABBAR', num: 33, col: C.gold, trim: C.bg, numCol: C.ink, numStroke: C.bg },
  lebron:  { name: 'JAMES', num: 23, col: N.mix(C.acc, C.bg, 0.45), trim: C.gold, numCol: C.gold, numStroke: C.bg },
  jordan:  { name: 'JORDAN', num: 23, col: C.acc, trim: C.bg, numCol: C.ink, numStroke: C.bg },
  blank:   { name: '', num: '?', col: N.mix(C.bg, C.sub, 0.3), trim: C.sub, numCol: C.sub, numStroke: C.bg },
};
NB.J = J;
// 柜子顺序：左→右 10..1；第 i 号柜（排名）在世界里的 x
const ORDER = ['curry', 'shaq', 'duncan', 'bird', 'wilt', 'russell', 'magic', 'kareem', 'lebron', 'jordan'];
const lockerX = rank => 960 + (10 - rank - 4.5) * 178;
NB.lockerX = lockerX; NB.ORDER = ORDER;

// 背景墙（更衣室）：竖向护墙板＋顶灯光束
const room = (c, s, opt = {}) => {
  c.fillStyle = N.D.wall; c.fillRect(-1200, -800, W + 2400, H + 1600);
  for (let x = -1200; x < W + 1200; x += 64) { c.fillStyle = rgba(C.bg, 0.25); c.fillRect(x, -800, 3, H + 1600); }
  c.fillStyle = N.D.walnutD; c.fillRect(-1200, 870, W + 2400, 400);                 // 长凳
  c.fillStyle = N.D.walnut; c.fillRect(-1200, 850, W + 2400, 34); c.fillStyle = rgba(C.gold, 0.25); c.fillRect(-1200, 850, W + 2400, 4);
  c.fillStyle = N.dk(C.surf, 0.35); c.fillRect(-1200, 950, W + 2400, 400);          // 地板
  (opt.lamps || [960]).forEach(x => N.beam(c, x, -80, 60, 520, 980, 0.045));
};
// 一排更衣柜
const lockers = (c, s, p) => {
  const filled = p.filled || {}, open = p.open || {}, plates = p.plates || {}, hl = p.hl;
  for (let rank = 10; rank >= 1; rank--) {
    const x = lockerX(rank), y0 = 120, w = 160, h = 700;
    c.fillStyle = N.D.walnutD; c.fillRect(x - w / 2 - 6, y0 - 6, w + 12, h + 12);
    c.fillStyle = rgba(C.bg, 0.9); c.fillRect(x - w / 2, y0 + 70, w, h - 70);             // 柜膛
    N.pool(c, x, y0 + 110, 60, 20, 0.05, 2);
    // 号码牌（顶）
    N.plate(c, x, y0 + 34, 92, 50, String(rank), 1, { font: F(36) });
    c.strokeStyle = N.D.brass; c.lineWidth = 5; c.beginPath(); c.moveTo(x - 30, y0 + 120); c.lineTo(x + 30, y0 + 120); c.stroke();   // 挂杆
    const who = filled[rank];
    if (who) { const k = typeof who === 'object' ? who : { id: who };
      const hp = k.at != null ? inn(s, k.at, 0.7, MO.cubicOut) : 1;      // 挂进去的动作
      if (hp > 0) { const yy = lerp(y0 - 420, y0 + 360, hp); N.hanger(c, x, yy, 0.42); N.jersey(c, x, yy, 0.42, J[k.id], { t: s, ph: rank }); } }
    // 门（左铰链）：open 0 关 1 全开
    const op = open[rank] != null ? (typeof open[rank] === 'number' ? open[rank] : clamp(MO.cubicInOut(clamp((s - open[rank][0]) / (open[rank][2] || 0.8))) * (open[rank][1] - (open[rank][3] ?? 0)) + (open[rank][3] ?? 0))) : (who ? 1 : 0);
    const dw = w * Math.cos(op * Math.PI * 0.46);
    c.fillStyle = N.D.walnut; c.beginPath(); c.moveTo(x - w / 2, y0 + 70); c.lineTo(x - w / 2 + dw, y0 + 70 + op * 26); c.lineTo(x - w / 2 + dw, y0 + h - op * 26); c.lineTo(x - w / 2, y0 + h); c.closePath(); c.fill();
    if (op < 0.98) { // 百叶
      c.strokeStyle = rgba(C.bg, 0.45); c.lineWidth = 4; for (let k = 0; k < 6; k++) { const yy = y0 + 110 + k * 18; c.beginPath(); c.moveTo(x - w / 2 + 24 * (dw / w), yy + op * 8); c.lineTo(x - w / 2 + dw - 24 * (dw / w), yy + op * 8); c.stroke(); }
      c.fillStyle = N.D.brass; c.fillRect(x - w / 2 + dw - 20 * (dw / w), y0 + 380, 8 * Math.max(0.3, dw / w), 50); }
    // 名牌（底）
    const pl = plates[rank]; const pp = pl ? (pl.at != null ? clamp((s - pl.at) / 0.8) : 1) : 0;
    c.fillStyle = N.D.walnutD; c.fillRect(x - w / 2 - 6, y0 + h + 6, w + 12, 54);
    if (pl) N.plate(c, x, y0 + h + 33, 148, 40, pl.text, MO.step(pp, 12), { font: F(26) });
    if (hl === rank) { c.strokeStyle = rgba(C.gold, 0.8); c.lineWidth = 4; c.strokeRect(x - w / 2 - 14, y0 - 14, w + 28, h + 82); }
  }
};
K.lockers = (c, s, p, d) => { room(c, s, { lamps: [lockerX(9), lockerX(5), lockerX(2)] }); lockers(c, s, p);
  if (p.hand) { const h = p.hand, hp = inn(s, h.at, 0.7); const x = lockerX(h.rank), y = lerp(1300, 520, hp) - inn(s, h.at + 1.0, 0.5) * -380;
    N.hand(c, x + 30, y, 0.9, -0.15, 'grip'); }
  if (p.ball) { const b = p.ball; const e = inn(s, b.at || 0, b.dur || 1.6, MO.cubicOut); const x = lerp(b.x0, b.x1, e); N.ball(c, x, 905, 34, (x - b.x0) / 34, { floorY: 940 }); }
};

// 球馆远景：看台＋木地板＋（可选）滚动的球
K.arena = (c, s, p, d) => {
  const hy = 560; N.stands(c, hy, { banners: p.banners, t: s }); N.floorPersp(c, hy, { centerV: 0.42 });
  N.beam(c, 960, -100, 80, 700, H, 0.04); N.pool(c, 960, 860, 520, 120, 0.06, 4);
  if (p.ball) { const b = p.ball, e = inn(s, b.at || 0, b.dur || d, b.ease ? MO[b.ease] : MO.linear); const x = lerp(b.x0, b.x1, e), y = lerp(b.y0 ?? 880, b.y1 ?? 880, e), r = lerp(b.r0 || 40, b.r1 || 40, e);
    N.ball(c, x, y, r, (x - b.x0) / r); }
  if (p.label) N.tag(c, p.label.x, p.label.y, 1, p.label.text);
};
// 球员通道：透视走廊，顶灯一盏盏掠过，尽头一扇门
K.tunnel = (c, s, p, d) => {
  c.fillStyle = N.D.wall; c.fillRect(-600, -400, W + 1200, H + 800);
  const vx = 960, vy = 470; const fr = (k) => ({ x0: lerp(-300, vx - 150, k), x1: lerp(W + 300, vx + 150, k), y0: lerp(-200, vy - 140, k), y1: lerp(H + 200, vy + 170, k) });
  for (let i = 8; i >= 0; i--) { const k = 1 - Math.pow(0.78, i + ((s * 0.35) % 1)); const f = fr(k);
    c.fillStyle = i % 2 ? N.D.wall2 : N.D.wall; c.fillRect(f.x0, f.y0, f.x1 - f.x0, f.y1 - f.y0);
    c.fillStyle = rgba(C.gold, 0.18 * (1 - k)); ell(c, vx, f.y0 + 20, (f.x1 - f.x0) * 0.12, 8); c.fill(); }
  const f = fr(0.97); c.fillStyle = N.D.walnut; c.fillRect(vx - 70, vy - 110, 140, 280); c.fillStyle = rgba(C.gold, 0.8); c.fillRect(vx - 70, vy + 165, 140, 5);
  c.fillStyle = N.D.brass; ell(c, vx + 45, vy + 40, 7, 7); c.fill();
  N.tag(c, vx, vy - 150, 0.8, p.sign || '更衣室', { string: false, font: ZH(30) });
  // 地板
  c.fillStyle = N.dk(C.surf, 0.1); c.beginPath(); c.moveTo(-300, H + 200); c.lineTo(W + 300, H + 200); c.lineTo(vx + 150, vy + 170); c.lineTo(vx - 150, vy + 170); c.fill();
  for (let i = -6; i <= 6; i++) { c.strokeStyle = rgba(C.bg, 0.3); c.lineWidth = 2; c.beginPath(); c.moveTo(vx + i * 230, H + 200); c.lineTo(vx + i * 25, vy + 170); c.stroke(); }
  if (p.ball !== false) { const e = inn(s, 0, d, MO.sineOut || MO.cubicOut); const y = lerp(1000, vy + 150, e), r = lerp(70, 10, e); N.ball(c, vx + Math.sin(e * 3) * 30 * (1 - e), y, r, e * 18); }
};
// 球衣特写：挂着、摆动；可选一只手把它挂上去/抚平
K.jersey = (c, s, p, d) => {
  room(c, s, { lamps: [960] }); c.fillStyle = rgba(C.bg, 0.92); c.fillRect(560, -100, 800, 1100); N.pool(c, 960, 170, 260, 50, 0.06, 3);
  c.strokeStyle = N.D.brass; c.lineWidth = 10; c.beginPath(); c.moveTo(780, 140); c.lineTo(1140, 140); c.stroke();
  const ent = p.enter != null ? inn(s, p.enter, 0.8) : 1; const y = lerp(-300, 560, ent);
  N.hanger(c, 960, y, 1.6); N.jersey(c, 960, y, 1.6, J[p.who], { t: s });
  if (p.hand) { const hp = p.enter != null ? clamp(1 - inn(s, p.enter + 0.9, 0.6)) : inn(s, p.handAt || 0.4, 0.6) * (1 - inn(s, d - 0.8, 0.5));
    N.hand(c, 960 + 40, y - 330 - 40 + (1 - hp) * -600, 1.3, Math.PI, 'grip'); }
  (p.tags || []).forEach((t, i) => { const a = pop(s, t.at, 0.4); if (a > 0) { c.save(); c.globalAlpha = clamp(a); N.tag(c, t.x ?? (i % 2 ? 1430 : 490), (t.y ?? 380 + i * 150) + (1 - a) * 30, 1, t.text); c.restore(); } });
};
// 四把尺子：木尺并排躺在地板上，当前那把滑出、发亮
const RULERS = [['戒指', 'ring'], ['巅峰', 'peak'], ['长度', 'tape'], ['时代', 'era']];
K.rulers = (c, s, p, d) => {
  N.planksFlat(c, -200, -200, W + 400, H + 400, 11);
  N.pool(c, 960, 540, 900, 420, 0.05, 4);
  const show = p.show ?? 4;
  RULERS.forEach(([name, ic], i) => {
    if (i >= show && !(p.appear && p.appear[i] != null)) return;
    const ap = p.appear && p.appear[i] != null ? inn(s, p.appear[i], 0.6) : 1; if (ap <= 0) return;
    const act = p.active === i ? inn(s, p.activeAt || 0.2, 0.6) : 0;
    const y = 250 + i * 180, x = 960 + act * 40 - (1 - ap) * 1400;
    c.save(); c.translate(x, y); c.rotate(-0.02 + i * 0.01);
    c.fillStyle = rgba(C.bg, 0.4); rr(c, -720 + 10, -50 + 14, 1440, 100, 8); c.fill();
    c.fillStyle = act > 0.1 ? N.mix(C.gold, C.surf, 0.2) : N.mix(C.surf, C.gold, 0.35); rr(c, -720, -50, 1440, 100, 8); c.fill();
    for (let k = 0; k <= 60; k++) { c.fillStyle = rgba(C.bg, 0.7); const hh = k % 10 === 0 ? 40 : k % 5 === 0 ? 28 : 16; c.fillRect(-560 + k * 21.5, -50, 3, hh);
      if (k % 10 === 0 && k < 60) text(c, String(k / 10), -560 + k * 21.5, 22, F(24, 'RobotoCondensed'), rgba(C.bg, 0.8)); }
    // 端头图标
    c.fillStyle = C.bg; rr(c, -720, -50, 150, 100, 8); c.fill();
    if (ic === 'ring') N.ring(c, -645, 4, 0.48); else if (ic === 'peak') { c.fillStyle = C.gold; c.beginPath(); c.moveTo(-700, 32); c.lineTo(-660, -26); c.lineTo(-640, 0); c.lineTo(-618, -36); c.lineTo(-590, 32); c.fill(); }
    else if (ic === 'tape') { c.fillStyle = C.gold; ell(c, -645, 0, 34, 34); c.fill(); c.fillStyle = C.bg; ell(c, -645, 0, 12, 12); c.fill(); }
    else { c.strokeStyle = C.gold; c.lineWidth = 6; ell(c, -645, 0, 32, 32); c.stroke(); c.beginPath(); c.moveTo(-645, 0); c.lineTo(-645, -22); c.moveTo(-645, 0); c.lineTo(-630, 8); c.stroke(); }
    // 填充（给某个人量出来的长度）
    if (p.fill && p.fill[i] != null) { const fv = p.fill[i], fp = inn(s, (p.fillAt || 0.4) + i * 0.25, 0.9, MO.cubicInOut);
      c.fillStyle = rgba(C.acc, 0.85); rr(c, -560, -14, 1110 * fv * fp, 28, 6); c.fill();
      if (p.fill2 && p.fill2[i] != null) { const f2 = p.fill2[i], fp2 = inn(s, (p.fillAt || 0.4) + 0.12 + i * 0.25, 0.9, MO.cubicInOut); c.fillStyle = rgba(C.ink, 0.9); rr(c, -560, 18, 1110 * f2 * fp2, 14, 5); c.fill(); } }
    c.fillStyle = act > 0.1 ? N.mix(C.gold, C.surf, 0.2) : N.mix(C.surf, C.gold, 0.35); rr(c, 560, -44, 150, 88, 6); c.fill();
    text(c, name, 690, 18, ZH(46), act > 0.1 ? C.bg : rgba(C.bg, 0.85), 'right');
    c.restore();
  });
  if (p.legend) p.legend.forEach((l, i) => { c.fillStyle = i ? C.ink : C.acc; rr(c, 300 + i * 420, 1000, 60, 22, 6); c.fill(); text(c, l, 380 + i * 420, 1022, ZH(34), C.ink, 'left'); });
  if (p.ball) N.ball(c, lerp(-100, 1650, inn(s, 0, d * 0.8, MO.cubicOut)), 990, 44, s * 6);
};
// 戒指托盘：n 枚戒指依次落下
K.rings = (c, s, p, d) => {
  N.planksFlat(c, -200, -200, W + 400, H + 400, 21, N.D.walnutD);
  const n = p.n, cols = Math.min(n, p.cols || 6), rows = Math.ceil(n / cols), sc = p.scale || (n > 6 ? 0.95 : 1.15);
  const tw = cols * 210 * sc + 80, th = rows * 230 * sc + 80;
  c.fillStyle = rgba(C.bg, 0.5); rr(c, 960 - tw / 2 + 14, 540 - th / 2 + 18, tw, th, 24); c.fill();
  c.fillStyle = N.D.velvet; rr(c, 960 - tw / 2, 540 - th / 2, tw, th, 24); c.fill(); N.pool(c, 960, 520, tw * 0.5, th * 0.45, 0.05, 3);
  const t0 = p.at ?? 0.3, gap = p.gap ?? Math.min(0.35, (d - t0 - 1) / Math.max(1, n));
  for (let i = 0; i < n; i++) { const cx = 960 + ((i % cols) - (cols - 1) / 2) * 210 * sc, cy = 540 + (Math.floor(i / cols) - (rows - 1) / 2) * 230 * sc;
    c.fillStyle = rgba(C.bg, 0.55); ell(c, cx, cy + 40 * sc, 60 * sc, 18 * sc); c.fill();
    const a = clamp((s - t0 - i * gap) / 0.3); if (a <= 0) continue; const yy = cy - (1 - MO.cubicIn(a)) * 500 + (a >= 1 ? 0 : 0);
    N.ring(c, cx, yy, 0.95 * sc, { year: p.years ? p.years[i] : null, gem: p.gems && p.gems[i] ? C.ink : C.acc }); }
  const cnt = Math.min(n, Math.floor((s - t0) / gap + 1)); if (p.counter !== false && cnt > 0) { N.tag(c, 960, 540 + th / 2 + 90, 1, `${p.label || '总冠军'} × ${cnt}`, { string: false, font: ZH(44) }); }
};
// 奖杯架：groups = [{kind, n, label}]
K.trophies = (c, s, p, d) => {
  room(c, s, { lamps: [560, 1360] }); const gs = p.groups, tot = gs.reduce((a, g) => a + g.n, 0);
  c.fillStyle = N.D.walnut; c.fillRect(100, 760, 1720, 30); c.fillStyle = rgba(C.gold, 0.3); c.fillRect(100, 760, 1720, 4); c.fillStyle = N.D.walnutD; c.fillRect(100, 790, 1720, 40);
  const sp = 120 * (p.scale || 1); let k = 0, x = 960 - (tot * sp + (gs.length - 1) * 120) / 2 + sp / 2; const t0 = p.at ?? 0.2, gap = p.gap ?? Math.min(0.28, (d - t0 - 1.2) / tot);
  gs.forEach(g => { const gx0 = x; for (let i = 0; i < g.n; i++) { const a = pop(s, t0 + k * gap, 0.35); if (a > 0) { c.save(); c.translate(x, 760); c.scale(1, clamp(a, 0, 1.2)); N.trophy(c, 0, 0, (g.kind === 'title' ? 0.85 : 0.95) * (p.scale || 1), g.kind); c.restore(); } x += sp; k++; }
    const lp = clamp((s - t0 - (k - 1) * gap) / 0.4); if (lp > 0) { c.save(); c.globalAlpha = lp; N.tag(c, (gx0 + x - sp) / 2, 900, 1, `${g.label} ×${g.n}`, { font: ZH(36) }); c.restore(); } x += 120; });
};
// 记分板：一块挂在暗处的翻牌板，数字在 hit 时刻翻出来
K.board = (c, s, p, d) => {
  c.fillStyle = C.bg; c.fillRect(-600, -400, W + 1200, H + 800);
  N.beam(c, 960, -200, 60, 760, 1100, 0.04);
  const n = p.value.length, bw = Math.max(760, n * 112 + 180), bh = p.sub ? 520 : 440;
  c.fillStyle = N.D.wall2; rr(c, 960 - bw / 2 - 30, 300 - 40, bw + 60, bh + 80, 24); c.fill();
  c.strokeStyle = N.D.brass; c.lineWidth = 6; rr(c, 960 - bw / 2 - 30, 260, bw + 60, bh + 80, 24); c.stroke();
  c.fillStyle = N.D.brass; c.fillRect(940, -400, 6, 660); c.fillRect(974, -400, 6, 660);
  // 灯泡点阵边框
  for (let i = 0; i < 26; i++) { const x = 960 - bw / 2 + i * bw / 25; const on = (Math.floor(s * 6) + i) % 3 !== 0; c.fillStyle = on ? C.gold : N.D.brassD; ell(c, x, 290, 6, 6); c.fill(); ell(c, x, 290 + bh + 20, 6, 6); c.fill(); }
  text(c, p.label, 960, 380, ZH(52), C.ink);
  N.flipDigits(c, 960, 520, p.value, s, p.hit ?? 0.6, { from: p.from, cw: 104, ch: 170, col: p.col || C.ink });
  if (p.sub) text(c, p.sub, 960, 700, ZH(40, 'Bold'), C.sub);
  if (p.ball) N.ball(c, 960 + bw / 2 + 120, 980, 50, s);
};
// 俯视半场：shots 点阵、路线
K.court = (c, s, p, d) => {
  N.planksFlat(c, -400, -300, W + 800, H + 600, 31, C.surf, 40);
  const bx = 960, by = 120, sc = 1.1; c.save(); c.translate(bx, by); c.scale(sc, sc);
  c.strokeStyle = rgba(C.ink, 0.85); c.lineWidth = 5;
  c.strokeRect(-700, 0, 1400, 1000);
  c.fillStyle = rgba(C.acc, 0.35); c.fillRect(-160, 0, 320, 400); c.strokeRect(-160, 0, 320, 400);
  c.beginPath(); c.arc(0, 400, 120, 0, Math.PI); c.stroke();
  c.beginPath(); c.moveTo(-620, 0); c.lineTo(-620, 210); c.arc(0, 110, 630, Math.PI - 0.17, 0.17, true); c.lineTo(620, 0); c.stroke();
  c.lineWidth = 6; c.beginPath(); c.moveTo(-60, 40); c.lineTo(60, 40); c.stroke(); c.strokeStyle = C.acc; ell(c, 0, 62, 20, 20); c.stroke();
  const r = U.rng(p.seed || 5), mode = p.mode || 'threes', n = p.n || 60, t0 = p.at ?? 0.2, span = p.span ?? (d - t0 - 0.6);
  for (let i = 0; i < n; i++) { let x, y;
    if (mode === 'threes') { const a = Math.PI * (0.06 + r() * 0.88), R = 680 + r() * 170; x = Math.cos(a) * R; y = 110 + Math.sin(a) * R; if (y > 960) continue; }
    else if (mode === 'deep') { const a = Math.PI * (0.1 + r() * 0.8), R = 820 + r() * 160; x = Math.cos(a) * R; y = 110 + Math.sin(a) * R; if (y > 980 || Math.abs(x) > 690) continue; }
    else if (mode === 'paint') { x = (r() - 0.5) * 260; y = 40 + r() * 230; }
    else { x = (r() - 0.5) * 1100; y = 60 + r() * 700; }
    const a = pop(s, t0 + (i / n) * span, 0.3); if (a <= 0) continue;
    c.fillStyle = (p.hot && mode !== 'paint') ? C.gold : C.ink; ell(c, x, y, 13 * clamp(a, 0, 1.3), 13 * clamp(a, 0, 1.3)); c.fill(); c.strokeStyle = rgba(C.bg, 0.6); c.lineWidth = 2; c.stroke(); c.strokeStyle = rgba(C.ink, 0.85); c.lineWidth = 5; }
  if (p.arrow) { const e = inn(s, p.arrow.at || 0.4, 1.0, MO.cubicInOut); const pts = p.arrow.pts; c.strokeStyle = C.acc; c.lineWidth = 9; c.setLineDash([24, 16]); c.beginPath();
    for (let i = 0; i <= 40 * e; i++) { const q = i / 40 * (pts.length - 1), k = Math.floor(q), f = q - k, a = pts[k], b = pts[Math.min(pts.length - 1, k + 1)]; const x = lerp(a[0], b[0], f), y = lerp(a[1], b[1], f); i ? c.lineTo(x, y) : c.moveTo(x, y); } c.stroke(); c.setLineDash([]); }
  c.restore();
  if (p.label) N.tag(c, p.label.x ?? 1600, p.label.y ?? 900, 1, p.label.text);
  if (p.ball) { const e = inn(s, p.ball.at || 0.3, p.ball.dur || 1.2, MO.cubicInOut); N.ball(c, lerp(p.ball.x0, 960, e), lerp(p.ball.y0, 188, e) - Math.sin(e * Math.PI) * 260, lerp(56, 34, e), s * 5, { shadow: false }); }
};
// 侧面篮筐：投篮轨迹、空心入网、擦板、天勾、扣篮
K.hoop = (c, s, p, d) => { c.save(); c.translate(960, 560); c.scale(1.4, 1.4); c.translate(-960, -480); hoopIn(c, s, p, d); c.restore(); };
const hoopIn = (c, s, p, d) => {
  room(c, s, { lamps: [1300] }); c.fillStyle = N.dk(C.surf, 0.12); c.fillRect(-600, 950, W + 1200, 400);
  // 篮架
  const hx = p.flip ? 600 : 1320, sg = p.flip ? -1 : 1, ry = 430;
  c.fillStyle = N.D.walnutD; c.fillRect(hx + sg * 230 - 18, 180, 36, 800);
  c.fillStyle = rgba(C.ink, 0.9); c.fillRect(hx + sg * 150 - 9, 200, 18, 290); c.strokeStyle = C.acc; c.lineWidth = 5; c.strokeRect(hx + sg * 150 - 9, 330, 18, 100);
  c.fillStyle = N.D.brassD; c.fillRect(Math.min(hx + sg * 150, hx + sg * 230), 300, 80, 20);
  // 球的轨迹
  const mode = p.mode || 'swish', t0 = p.at ?? 0.3, dur = p.dur ?? 1.3, e = clamp((s - t0) / dur);
  const sx = p.sx ?? (hx - sg * 900), sy = p.sy ?? 700, peak = p.peak ?? 120;
  let bx, by, net = 0;
  if (mode === 'bank') { const k1 = 0.7; if (e < k1) { const q = e / k1; bx = lerp(sx, hx + sg * 138, q); by = lerp(sy, 360, q) - Math.sin(q * Math.PI) * peak; } else { const q = (e - k1) / (1 - k1); bx = lerp(hx + sg * 138, hx, q); by = lerp(360, ry + 80, MO.cubicIn(q)); net = q; } }
  else if (mode === 'dunk') { const q = MO.cubicIn(e); bx = lerp(sx, hx, MO.cubicOut(e)); by = lerp(sy, ry - 120, MO.cubicOut(e)) + (e > 0.75 ? (e - 0.75) / 0.25 * 220 : 0); net = e > 0.75 ? (e - 0.75) / 0.25 : 0; }
  else if (mode === 'miss') { bx = lerp(sx, hx - sg * 50, Math.min(e, 1)); by = lerp(sy, ry - 6, e) - Math.sin(e * Math.PI) * (peak + Math.abs(sx - hx) * 0.35); if (e >= 1) { const f = clamp((s - t0 - dur) / 0.7); bx = hx - sg * 50 - sg * f * 380; by = ry - 6 - Math.sin(f * Math.PI) * 140 + f * f * 500; } }
  else { bx = lerp(sx, hx, e); by = lerp(sy, ry + 10, e) - Math.sin(e * Math.PI) * (peak + Math.abs(sx - hx) * 0.35); if (e > 0.88) net = (e - 0.88) / 0.12; if (e >= 1) { const f = clamp((s - t0 - dur) / 0.4); by = ry + 10 + f * 420; bx = hx; net = 1 - f * 0.5; } }
  // 出手的手（天勾：高举的手臂）
  if (p.hand) { const hp = clamp(1 - (s - t0) / 0.5); const hxp = sx - sg * 10, hyp = sy + 60;
    if (mode === 'hook') { c.save(); c.translate(hxp, hyp + 520); c.rotate(sg * 0.25); c.fillStyle = D.cuff; rr(c, -48, -560, 96, 700, 40); c.fill(); c.restore(); N.hand(c, hxp + sg * 60, hyp - 20, 1.1, sg * 0.3, e > 0 ? 'open' : 'grip'); }
    else N.hand(c, hxp, hyp + 80 + (1 - hp) * 30, 1.2 * (p.handScale || 1), sg * 0.15, e > 0.05 ? 'open' : 'grip'); }
  if (s >= t0 - 0.01 || p.hold) { const r = 42; N.ball(c, s < t0 ? sx : bx, s < t0 ? sy : by, r, s * 7 * sg, { shadow: false }); }
  // 篮筐（画在球前面的半圈）＋网
  c.strokeStyle = N.dk(C.acc, 0.2); c.lineWidth = 9; ell(c, hx, ry, 68, 14); c.stroke();
  const sw = Math.sin(net * Math.PI) * 26;
  c.strokeStyle = rgba(C.ink, 0.85); c.lineWidth = 3; for (let i = -4; i <= 4; i++) { c.beginPath(); c.moveTo(hx + i * 16, ry + 6); c.quadraticCurveTo(hx + i * 12 + sw * 0.3, ry + 70 + sw, hx + i * 8, ry + 120 + sw * 0.6); c.stroke(); }
  for (let k = 1; k <= 3; k++) { c.beginPath(); c.moveTo(hx - 64 + k * 8, ry + k * 34 + sw * k / 3); c.lineTo(hx + 64 - k * 8, ry + k * 34 + sw * k / 3); c.stroke(); }
  c.strokeStyle = C.acc; c.lineWidth = 9; c.beginPath(); c.ellipse(hx, ry, 68, 14, 0, 0, Math.PI); c.stroke();
  if (p.clock) { const v = Math.max(p.clockMin ?? 0, p.clock - Math.max(0, s - (p.clockAt || 0))); text(c, v.toFixed(1), p.flip ? 1500 : 380, 220, F(150, 'RobotoCondensed'), C.acc); }
  if (p.label) N.tag(c, p.label.x ?? (p.flip ? 1500 : 420), p.label.y ?? 860, 1, p.label.text);
};
// 天平：左右两盘放东西，横梁慢慢倾斜到 tilt（弧度，正 = 右沉）
K.scale = (c, s, p, d) => {
  room(c, s, { lamps: [960] }); N.pool(c, 960, 960, 600, 60, 0.06, 3);
  const cx = 960, cy = 260, tilt = (p.tilt0 ?? 0) + ((p.tilt ?? 0) - (p.tilt0 ?? 0)) * inn(s, p.tiltAt ?? 0.6, p.tiltDur ?? 1.6, MO.cubicInOut) + Math.sin(s * 2.2) * 0.006;
  c.fillStyle = N.D.walnutD; rr(c, cx - 130, 900, 260, 60, 10); c.fill(); c.fillStyle = N.D.brassD; c.fillRect(cx - 14, cy, 28, 650); c.fillStyle = C.gold; c.fillRect(cx - 9, cy, 18, 650);
  const L = 560; const ex = Math.cos(tilt) * L, ey = Math.sin(tilt) * L;
  c.strokeStyle = C.gold; c.lineWidth = 16; c.lineCap = 'round'; c.beginPath(); c.moveTo(cx - ex, cy - ey); c.lineTo(cx + ex, cy + ey); c.stroke();
  c.fillStyle = C.gold; ell(c, cx, cy, 26, 26); c.fill();
  [[-1, p.left || []], [1, p.right || []]].forEach(([sg, items]) => { const px = cx + sg * ex, py = cy + sg * ey;
    c.strokeStyle = rgba(C.gold, 0.8); c.lineWidth = 3; c.beginPath(); c.moveTo(px, py); c.lineTo(px - 170, py + 300); c.moveTo(px, py); c.lineTo(px + 170, py + 300); c.stroke();
    c.fillStyle = N.D.brassD; c.beginPath(); c.ellipse(px, py + 300, 200, 34, 0, 0, Math.PI); c.fill(); c.fillStyle = C.gold; ell(c, px, py + 300, 200, 22); c.fill();
    items.forEach((it, i) => { const a = pop(s, it.at ?? 0.2, 0.35); if (a <= 0) return; const ix = px + (i - (items.length - 1) / 2) * (it.dx || 110), iy = py + 292 - (1 - clamp(a)) * 300;
      c.save(); c.translate(ix, iy);
      if (it.k === 'ring') N.ring(c, 0, -34, 0.55); else if (it.k === 'num') { c.fillStyle = N.D.walnutD; rr(c, -70, -110, 140, 104, 10); c.fill(); text(c, it.v, 0, -40, F(it.v.length > 3 ? 46 : 62), C.ink); }
      else if (it.k === 'jersey') N.jersey(c, 0, -130, 0.4, J[it.who], { flat: true }); else if (it.k === 'trophy') N.trophy(c, 0, 0, 0.5, it.v || 'title');
      c.restore(); });
    if (sg < 0 ? p.labelL : p.labelR) N.tag(c, px, py + 420, 1, sg < 0 ? p.labelL : p.labelR, { string: false }); });
};
// 系列赛记分牌：一排比赛格子，W/L 依次翻出
K.series = (c, s, p, d) => {
  c.fillStyle = C.bg; c.fillRect(-600, -400, W + 1200, H + 800); N.planksFlat(c, -300, 660, W + 600, 700, 41);
  N.beam(c, 960, -100, 80, 760, 700, 0.04);
  const g = p.games, n = g.length, w = Math.min(190, 1640 / n - 26), gap = 26, x0 = 960 - (n * w + (n - 1) * gap) / 2, t0 = p.at ?? 0.3, gp = p.gap ?? Math.min(0.55, (d - t0 - 1) / n);
  text(c, p.label, 960, 230, ZH(56), C.ink);
  g.forEach((r, i) => { const x = x0 + i * (w + gap), a = clamp((s - t0 - i * gp) / 0.3);
    c.fillStyle = N.D.walnutD; rr(c, x, 300, w, 260, 14); c.fill(); text(c, `G${i + 1}`, x + w / 2, 345, F(34, 'RobotoCondensed'), C.sub);
    if (a > 0) { c.save(); c.translate(x + w / 2, 460); c.scale(1, Math.abs(Math.cos((1 - a) * Math.PI / 2))); const win = r === 'W';
      c.fillStyle = win ? C.gold : N.mix(C.bg, C.sub, 0.3); rr(c, -w / 2 + 14, -80, w - 28, 160, 10); c.fill(); text(c, win ? '胜' : '负', 0, 34, ZH(Math.min(96, w * 0.55)), win ? C.bg : C.sub); c.restore(); } });
  const wins = g.slice(0, Math.max(0, Math.floor((s - t0) / gp + 1))).filter(x => x === 'W').length, loss = Math.max(0, Math.min(n, Math.floor((s - t0) / gp + 1))) - wins;
  if (p.score !== false && s > t0) text(c, `${wins} : ${loss}`, 960, 760, F(150, 'RobotoCondensed'), C.ink);
  if (p.ball) N.ball(c, lerp(-200, 1700, inn(s, 0.2, d - 0.4, MO.linear)), 940, 46, s * 5);
};
// 卷尺：从左向右拉出，刻度是年份；marks = [{y: 年, text}]
K.tape = (c, s, p, d) => {
  N.planksFlat(c, -400, -300, W + 800, H + 600, 51); N.pool(c, 960, 540, 900, 300, 0.05, 3);
  const y0 = p.y0 || 1990, y1 = p.y1 || 2010, span = y1 - y0, L = 1500, x0 = 210, e = inn(s, p.at ?? 0.1, p.dur ?? Math.min(2.4, d - 0.8), MO.cubicOut);
  const len = L * e;
  c.fillStyle = rgba(C.bg, 0.45); rr(c, x0 + 6, 532, len, 96, 4); c.fill();
  c.fillStyle = C.gold; rr(c, x0, 520, len, 96, 4); c.fill();
  c.save(); c.beginPath(); c.rect(x0, 500, len, 140); c.clip();
  for (let yr = y0; yr <= y1; yr++) { const x = x0 + (yr - y0) / span * L; c.fillStyle = C.bg; c.fillRect(x - 2, 520, 4, 40); if ((yr - y0) % (p.every || 5) === 0 || yr === y1) text(c, String(yr), x, 600, F(30, 'RobotoCondensed'), C.bg); }
  for (let k = 0; k < span * 4; k++) { const x = x0 + k / (span * 4) * L; c.fillStyle = rgba(C.bg, 0.7); c.fillRect(x - 1, 520, 2, 18); }
  c.restore();
  // 卷尺盒
  c.fillStyle = N.D.walnutD; rr(c, x0 + len - 20, 470, 190, 200, 40); c.fill(); c.fillStyle = C.acc; rr(c, x0 + len - 6, 484, 162, 172, 32); c.fill(); c.fillStyle = C.bg; ell(c, x0 + len + 75, 570, 30, 30); c.fill();
  (p.marks || []).forEach((m, i) => { const x = x0 + (m.y - y0) / span * L; if (x > x0 + len) return; const a = pop(s, (p.at ?? 0.1) + ((m.y - y0) / span) * (p.dur ?? 2) + 0.1, 0.4); if (a <= 0) return;
    c.save(); c.translate(x, 500 - (1 - clamp(a)) * 40); c.globalAlpha = clamp(a);
    if (m.ring) N.ring(c, 0, -90, 0.6); else { c.fillStyle = C.acc; c.beginPath(); c.moveTo(0, 0); c.lineTo(-16, -30); c.lineTo(16, -30); c.fill(); }
    if (m.text) N.tag(c, 0, m.ring ? -210 : -80 - (i % 2) * 70, 0.9, m.text, { font: ZH(30), string: false });
    c.restore(); });
  if (p.label) N.tag(c, 960, 860, 1, p.label, { string: false });
};
// 老式电视：屏幕里是雪花/录像字样
K.tv = (c, s, p, d) => {
  room(c, s, { lamps: [] }); c.fillStyle = rgba(C.bg, 0.55); c.fillRect(-600, -400, W + 1200, H + 800);
  c.fillStyle = N.D.walnut; rr(c, 560, 260, 800, 560, 40); c.fill(); c.fillStyle = N.D.walnutD; rr(c, 600, 300, 560, 480, 30); c.fill();
  // 屏
  c.save(); rr(c, 620, 320, 520, 440, 60); c.clip(); c.fillStyle = N.mix(C.bg, C.sub, 0.5); c.fillRect(620, 320, 520, 440);
  const r = U.rng(1 + Math.floor(s * 12)); for (let i = 0; i < 900; i++) { c.fillStyle = r() < 0.5 ? rgba(C.ink, 0.35) : rgba(C.bg, 0.4); c.fillRect(620 + r() * 520, 320 + r() * 440, 6, 3); }
  if (p.screen) { const a = inn(s, p.screenAt ?? 0.5, 0.3); c.globalAlpha = a; c.fillStyle = rgba(C.bg, 0.75); c.fillRect(620, 480, 520, 120); text(c, p.screen, 880, 562, ZH(64), C.gold); }
  if (p.ballOnScreen) N.ball(c, 880 + Math.sin(s * 3) * 120, 560 + Math.abs(Math.sin(s * 5)) * -90 + 60, 50, s * 4, { shadow: false });
  c.restore();
  N.pool(c, 880, 540, 380, 300, 0.035, 3);
  // 旋钮、天线
  c.fillStyle = N.D.brass; ell(c, 1250, 400, 34, 34); c.fill(); ell(c, 1250, 500, 34, 34); c.fill(); c.fillStyle = C.bg; c.fillRect(1240, 368, 20, 30);
  c.strokeStyle = N.D.brass; c.lineWidth = 6; c.beginPath(); c.moveTo(960, 262); c.lineTo(820 + Math.sin(s * 0.7) * 6, 80); c.moveTo(960, 262); c.lineTo(1120, 90); c.stroke();
  if (p.clock) { text(c, p.clock, 1500, 300, F(110, 'RobotoCondensed'), C.acc); }
  if (p.label) N.tag(c, 960, 930, 1, p.label, { string: false });
};
// 大巴：夜路上一辆老式大巴驶过
K.bus = (c, s, p, d) => {
  c.fillStyle = C.bg; c.fillRect(-600, -400, W + 1200, H + 800);
  const r = U.rng(9); for (let i = 0; i < 40; i++) { const x = ((r() * 3000 - s * 260 * (0.3 + r() * 0.4)) % 3000 + 3000) % 3000 - 600, y = 150 + r() * 420; c.fillStyle = rgba(C.gold, 0.25 + r() * 0.3); ell(c, x, y, 3, 3); c.fill(); }
  c.fillStyle = N.D.wall2; c.fillRect(-600, 760, W + 1200, 400);
  for (let i = 0; i < 12; i++) { const x = ((i * 260 - s * 520) % 3120 + 3120) % 3120 - 600; c.fillStyle = rgba(C.gold, 0.6); c.fillRect(x, 860, 120, 10); }
  const bx = lerp(-700, 2100, inn(s, 0, d, MO.linear)), by = 560;
  c.fillStyle = N.dk(C.gold, 0.25); rr(c, bx - 380, by, 760, 230, 50); c.fill(); c.fillStyle = C.gold; rr(c, bx - 380, by, 760, 120, 50); c.fill();
  for (let i = 0; i < 7; i++) { c.fillStyle = (i * 7 + 3) % 5 ? rgba(C.ink, 0.85) : N.mix(C.bg, C.sub, 0.3); rr(c, bx - 330 + i * 92, by + 30, 70, 64, 8); c.fill(); }
  c.fillStyle = C.bg; [-240, 250].forEach(dx => { ell(c, bx + dx, by + 232, 56, 56); c.fill(); c.fillStyle = N.D.brass; ell(c, bx + dx, by + 232, 20, 20); c.fill(); c.fillStyle = C.bg; });
  c.fillStyle = rgba(C.gold, 0.25); c.beginPath(); c.moveTo(bx + 380, by + 150); c.lineTo(bx + 900, by + 90); c.lineTo(bx + 900, by + 260); c.fill();
  if (p.sign) N.tag(c, bx, by - 50, 1, p.sign, { string: false, font: ZH(32) });
};
// 筹码柱：几个人的数量对比（每一枚是一片圆筹码，带编号）
K.stacks = (c, s, p, d) => {
  N.planksFlat(c, -300, -300, W + 600, H + 600, 61); N.pool(c, 960, 700, 800, 200, 0.05, 3);
  const cols = p.cols, n = cols.length, gap = Math.min(420, 1500 / n), x0 = 960 - (n - 1) * gap / 2, t0 = p.at ?? 0.3;
  cols.forEach((col, i) => { const x = x0 + i * gap, base = 800, per = p.step || 34; const sp = (p.span ?? (d - t0 - 1.2)) / Math.max(...cols.map(c => c.n));
    for (let k = 0; k < col.n; k++) { const a = clamp((s - t0 - i * 0.15 - k * sp) / 0.25); if (a <= 0) break; const y = base - k * per - (1 - MO.cubicIn(a)) * 300;
      c.fillStyle = N.dk(col.c || C.gold, 0.35); ell(c, x, y + 10, 92, 26); c.fill(); c.fillRect(x - 92, y - 4, 184, 14); c.fillStyle = col.c || C.gold; ell(c, x, y - 4, 92, 26); c.fill(); c.strokeStyle = rgba(C.bg, 0.4); c.lineWidth = 3; ell(c, x, y - 4, 60, 16); c.stroke(); }
    const shown = Math.max(0, Math.min(col.n, Math.floor((s - t0 - i * 0.15) / sp) + 1));
    text(c, String(shown), x, base - col.n * per - 70, F(84, 'RobotoCondensed'), col.c || C.gold);
    N.tag(c, x, base + 120, 1, col.label, { string: false, font: ZH(36) }); });
  if (p.title) text(c, p.title, 960, 120, ZH(52), C.ink);
};
// 选秀板：一列顺位格子，高亮某一个
K.draft = (c, s, p, d) => {
  c.fillStyle = N.D.wall; c.fillRect(-600, -400, W + 1200, H + 800);
  const rows = p.rows, t0 = p.at ?? 0.2; text(c, p.title, 960, 150, ZH(54), C.ink);
  rows.forEach((r, i) => { const y = 240 + i * 120, a = inn(s, t0 + i * 0.18, 0.4); const hl = p.hl === i;
    c.save(); c.translate((1 - a) * -300, 0); c.globalAlpha = a;
    c.fillStyle = hl ? C.gold : N.D.walnutD; rr(c, 460, y, 1000, 96, 10); c.fill();
    text(c, String(r.pick), 540, y + 70, F(60, 'RobotoCondensed'), hl ? C.bg : C.sub);
    text(c, r.name, 640, y + 66, r.zh ? ZH(46) : F(52), hl ? C.bg : C.ink, 'left'); c.restore(); });
  if (p.hlAt != null) { const a = pop(s, p.hlAt, 0.3); if (a > 0) { const y = 240 + p.hl * 120; c.strokeStyle = C.acc; c.lineWidth = 8; rr(c, 450 - 6 * a, y - 10, 1020 + 12 * a, 116, 14); c.stroke(); } }
};
// 拼数字：一个大数字刻在地板上（用于少数关键数字的砸入）
K.floorNum = (c, s, p, d) => {
  N.planksFlat(c, -400, -300, W + 800, H + 600, 71); N.pool(c, 960, 540, 760, 380, 0.06, 4);
  const a = MO.slam(s, p.hit ?? 0.3); c.save(); c.translate(960, 560); c.scale(a || 0.001, a || 0.001); c.globalAlpha = s >= (p.hit ?? 0.3) ? 1 : 0;
  c.font = F(p.size || 340); c.textAlign = 'center'; c.textBaseline = 'middle'; c.lineJoin = 'round'; c.strokeStyle = C.bg; c.lineWidth = 22; c.strokeText(p.value, 0, 0); c.fillStyle = p.col || C.ink; c.fillText(p.value, 0, 0); c.restore();
  if (p.sub) { const b = inn(s, (p.hit ?? 0.3) + 0.4, 0.4); c.globalAlpha = b; N.tag(c, 960, 880, 1, p.sub, { string: false }); c.globalAlpha = 1; }
  if (p.ball) N.ball(c, 960 + 520, 760, 60, s * 3);
};
})();
// ---------- 追加的镜头种类 ----------
(() => {
const N = NB, { W, H, TAU, C, D, rgba, F, ZH, rr, ell, text, inn, pop } = N, J = N.J;
const { clamp, lerp } = U;
J.dell = { name: 'CURRY', num: 30, col: N.mix(C.acc, C.bg, 0.2), trim: C.ink, numCol: C.ink, numStroke: C.bg };
J.horry = { name: 'HORRY', num: 5, col: C.gold, trim: C.bg, numCol: C.ink, numStroke: C.bg };
J.bowie = { name: 'BOWIE', num: 31, col: N.mix(C.bg, C.sub, 0.4), trim: C.ink, numCol: C.ink, numStroke: C.bg };
J.malone = { name: 'MALONE', num: 32, col: N.mix(C.bg, C.sub, 0.5), trim: C.gold, numCol: C.gold, numStroke: C.bg };
const wallBg = (c) => { c.fillStyle = D.wall; c.fillRect(-1200, -800, W + 2400, H + 1600); for (let x = -1200; x < W + 1200; x += 64) { c.fillStyle = rgba(C.bg, 0.25); c.fillRect(x, -800, 3, H + 1600); }
  c.fillStyle = N.dk(C.surf, 0.35); c.fillRect(-1200, 950, W + 2400, 400); c.fillStyle = D.walnut; c.fillRect(-1200, 930, W + 2400, 24); };
// 衣架横杆：几件球衣挂成一排，hl 那件被灯照亮，其余压暗
NBK.rack = (c, s, p, d) => { wallBg(c); const ws = p.who, n = ws.length, gap = Math.min(440, 1600 / n), x0 = 960 - (n - 1) * gap / 2;
  c.strokeStyle = D.brass; c.lineWidth = 12; c.beginPath(); c.moveTo(x0 - 240, 250); c.lineTo(x0 + (n - 1) * gap + 240, 250); c.stroke();
  ws.forEach((w, i) => { const x = x0 + i * gap, a = p.at != null ? inn(s, p.at + i * 0.25, 0.6) : 1; const y = lerp(-400, 560, a); const lit = p.hl == null || p.hl === i || (p.hlAt != null && s < p.hlAt);
    if (lit) N.pool(c, x, 260, 160, 30, 0.07, 3); N.hanger(c, x, y, 0.95); N.jersey(c, x, y, 0.95, J[w], { t: s, ph: i, dim: lit ? 0 : 0.55 });
    if (p.tags && p.tags[i]) N.tag(c, x, 880, 0.9, p.tags[i], { string: false, font: ZH(32) }); }); };
// 墙上的钟：指针转到 hh:mm，下面一颗球在空球馆地板上拍
NBK.clock = (c, s, p, d) => { wallBg(c); N.pool(c, 960, 990, 500, 60, 0.07, 3); N.beam(c, 960, -100, 50, 420, 980, 0.05);
  const cx = 960, cy = 360, R = 220; c.fillStyle = D.walnutD; ell(c, cx, cy, R + 24, R + 24); c.fill(); c.fillStyle = C.ink; ell(c, cx, cy, R, R); c.fill();
  for (let i = 0; i < 12; i++) { const a = i / 12 * TAU; c.fillStyle = C.bg; c.save(); c.translate(cx, cy); c.rotate(a); c.fillRect(-4, -R + 14, 8, i % 3 ? 22 : 40); c.restore(); }
  const e = inn(s, 0.2, p.spin ?? 1.6, MO.cubicInOut); const mins = lerp(p.from ?? 120, p.to ?? 240, e);
  const hand = (ang, len, w, col) => { c.save(); c.translate(cx, cy); c.rotate(ang); c.fillStyle = col; rr(c, -w / 2, -len, w, len + 20, w / 2); c.fill(); c.restore(); };
  hand(mins / 720 * TAU, R * 0.55, 16, C.bg); hand((mins % 60) / 60 * TAU, R * 0.82, 10, C.bg); c.fillStyle = C.acc; ell(c, cx, cy, 14, 14); c.fill();
  const by = 900 - Math.abs(Math.sin(s * 3.6)) * 260; N.ball(c, 1400, by, 46, s * 2, { floorY: 946 });
  if (p.label) N.tag(c, cx, 700, 1, p.label, { string: false }); };
// 投票箱：一张张选票落进去；missing 张空着
NBK.ballots = (c, s, p, d) => { wallBg(c); N.pool(c, 960, 700, 520, 120, 0.07, 3);
  const n = p.n || 20, cols = 10, t0 = p.at ?? 0.2, gap = p.gap ?? Math.min(0.12, (d - t0 - 1.4) / n);
  text(c, p.title || '', 960, 160, ZH(54), C.ink);
  for (let i = 0; i < n; i++) { const x = 960 + ((i % cols) - 4.5) * 150, y = 330 + Math.floor(i / cols) * 230; const miss = (p.missing || []).includes(i);
    c.strokeStyle = rgba(C.ink, 0.35); c.lineWidth = 3; c.setLineDash([8, 6]); rr(c, x - 55, y - 80, 110, 160, 8); c.stroke(); c.setLineDash([]);
    if (miss) { const a = pop(s, t0 + n * gap + 0.3, 0.4); if (a > 0) { c.strokeStyle = C.acc; c.lineWidth = 6; c.beginPath(); c.moveTo(x - 30, y - 30); c.lineTo(x + 30, y + 30); c.moveTo(x + 30, y - 30); c.lineTo(x - 30, y + 30); c.stroke(); } continue; }
    const a = clamp((s - t0 - i * gap) / 0.25); if (a <= 0) continue; c.save(); c.translate(x, y - (1 - MO.cubicOut(a)) * 200); c.rotate((i % 3 - 1) * 0.04);
    c.fillStyle = C.ink; rr(c, -52, -76, 104, 152, 6); c.fill(); c.fillStyle = rgba(C.bg, 0.5); for (let k = 0; k < 4; k++) c.fillRect(-36, -50 + k * 26, 72, 6);
    c.strokeStyle = C.acc; c.lineWidth = 7; c.beginPath(); c.moveTo(-20, 44); c.lineTo(-6, 58); c.lineTo(26, 26); c.stroke(); c.restore(); }
  const cnt = Math.max(0, Math.min(n - (p.missing || []).length, Math.floor((s - t0) / gap) + 1)); if (s > t0) N.tag(c, 960, 860, 1, `${cnt} / ${n}`, { string: false, font: F(48, 'RobotoCondensed') }); };
// 三张名单：钉在墙上的三张纸，各 10 行；同一行用红线连起来（重合）；mode 'swap' 时有两行互换位置
NBK.lists = (c, s, p, d) => { wallBg(c); const xs = [520, 960, 1400], t0 = p.at ?? 0.2;
  xs.forEach((x, k) => { const a = inn(s, t0 + k * 0.25, 0.5); c.save(); c.translate(x, 540 + (1 - a) * 700); c.rotate((k - 1) * 0.03);
    c.fillStyle = rgba(C.bg, 0.4); c.fillRect(-170 + 10, -380 + 14, 340, 760); c.fillStyle = C.ink; c.fillRect(-170, -380, 340, 760);
    c.fillStyle = C.acc; ell(c, 0, -360, 12, 12); c.fill(); text(c, p.heads ? p.heads[k] : '', 0, -300, ZH(34), C.bg);
    for (let i = 0; i < 10; i++) { let row = i; if (p.mode === 'swap' && k === (p.swapList ?? 1)) { const e = inn(s, p.swapAt ?? 1, 0.8, MO.cubicInOut); const [a1, b1] = p.swap || [8, 9]; if (i === a1) row = lerp(a1, b1, e); if (i === b1) row = lerp(b1, a1, e); }
      const y = -240 + row * 58; text(c, String(i + 1), -130, y + 12, F(30, 'RobotoCondensed'), N.mix(C.bg, C.sub, 0.4), 'left');
      c.fillStyle = (p.hot || []).includes(i) ? C.acc : rgba(C.bg, 0.7); rr(c, -90, y - 8, 230 - (i * 37 % 60), 22, 6); c.fill(); }
    c.restore(); });
  if (p.links) { const e = inn(s, p.linkAt ?? 1.2, 1.2); c.strokeStyle = rgba(C.acc, 0.8); c.lineWidth = 4; for (let i = 0; i < 10 * e; i++) { if ((p.skip || []).includes(i)) continue; const y = 540 - 240 + i * 58 + 3; c.beginPath(); c.moveTo(600, y); c.lineTo(880, y); c.moveTo(1040, y); c.lineTo(1320, y); c.stroke(); } } };
// 烟花与灯塔：左边一朵烟花炸开又熄灭，右边灯塔的光一直在扫
NBK.beacon = (c, s, p, d) => { c.fillStyle = C.bg; c.fillRect(-600, -400, W + 1200, H + 800);
  c.fillStyle = N.mix(C.bg, C.surf, 0.22); c.beginPath(); c.moveTo(-600, 860); for (let x = -600; x <= W + 600; x += 40) c.lineTo(x, 860 + Math.sin(x * 0.01 + s) * 8); c.lineTo(W + 600, H + 400); c.lineTo(-600, H + 400); c.fill();
  // 烟花
  const fx = 520, fy = 330, ph = (s % 3.2) / 3.2, r = U.rng(3);
  if (ph < 0.25) { const q = ph / 0.25; c.fillStyle = C.gold; ell(c, fx, lerp(860, fy, MO.cubicOut(q)), 6, 6); c.fill(); }
  else { const q = (ph - 0.25) / 0.75; for (let i = 0; i < 36; i++) { const a = i / 36 * TAU + r() * 0.1, R = MO.cubicOut(q) * (200 + r() * 60); c.fillStyle = rgba(i % 2 ? C.gold : C.acc, 1 - q);
      ell(c, fx + Math.cos(a) * R, fy + Math.sin(a) * R + q * q * 80, 7 * (1 - q * 0.6), 7 * (1 - q * 0.6)); c.fill(); } }
  // 灯塔
  const lx = 1400; c.fillStyle = C.ink; c.beginPath(); c.moveTo(lx - 70, 860); c.lineTo(lx - 44, 400); c.lineTo(lx + 44, 400); c.lineTo(lx + 70, 860); c.fill();
  c.fillStyle = C.acc; for (let k = 0; k < 3; k++) { const y = 480 + k * 130; c.beginPath(); c.moveTo(lx - 48 - k * 5, y); c.lineTo(lx + 48 + k * 5, y); c.lineTo(lx + 52 + k * 5, y + 50); c.lineTo(lx - 52 - k * 5, y + 50); c.fill(); }
  c.fillStyle = D.walnutD; c.fillRect(lx - 60, 330, 120, 70); c.fillStyle = C.gold; c.fillRect(lx - 40, 340, 80, 50); c.fillStyle = D.walnutD; c.beginPath(); c.moveTo(lx - 70, 330); c.lineTo(lx, 270); c.lineTo(lx + 70, 330); c.fill();
  const ang = Math.sin(s * 0.9) * 0.9 + Math.PI; c.save(); c.translate(lx, 365); c.rotate(ang); for (let k = 0; k < 3; k++) { c.fillStyle = rgba(C.gold, 0.07); c.beginPath(); c.moveTo(0, 0); c.lineTo(1500, -120 + k * 40); c.lineTo(1500, 120 - k * 40); c.fill(); } c.restore();
  if (p.tagL) N.tag(c, fx, 960, 1, p.tagL, { string: false }); if (p.tagR) N.tag(c, lx, 960, 1, p.tagR, { string: false }); };
// 篮球在指尖转：一只手特写
NBK.spin = (c, s, p, d) => { wallBg(c); N.pool(c, 960, 380, 380, 300, 0.05, 3); N.hand(c, 960, 640, 1.8, 0, 'point'); N.ball(c, 960, 380 - Math.abs(Math.sin(s * 2)) * 6, 120, s * 9, { shadow: false });
  if (p.label) N.tag(c, 1450, 760, 1, p.label, { string: false }); };
// 双人：两件球衣并排，可以让左边那件升走（exitL）
NBK.duo = (c, s, p, d) => { const r0 = NBK._duoRoom; wallBg(c); N.pool(c, 640, 230, 220, 40, 0.07, 3); N.pool(c, 1280, 230, 220, 40, 0.07, 3);
  const a = p.enterL != null ? inn(s, p.enterL, 0.8) : 1, b = p.enterR != null ? inn(s, p.enterR, 0.8) : 1, xl = p.exitL != null ? inn(s, p.exitL, 1.0, MO.cubicIn) : 0;
  const yl = lerp(-400, 540, a) - xl * 1000, yr = lerp(-400, 540, b);
  N.hanger(c, 640, yl, 1.1); N.jersey(c, 640, yl, 1.1, J[p.L], { t: s, dim: p.dimL || 0 });
  N.hanger(c, 1280, yr, 1.1); N.jersey(c, 1280, yr, 1.1, J[p.R], { t: s, ph: 2, dim: p.dimR || 0 });
  if (p.tagL) N.tag(c, 640, 880, 1, p.tagL, { string: false }); if (p.tagR) N.tag(c, 1280, 880, 1, p.tagR, { string: false });
  if (p.mid) { const e = pop(s, p.midAt ?? 0.8, 0.4); if (e > 0) text(c, p.mid, 960, 600, F(110 * clamp(e, 0, 1.2)), C.gold); } };
})();

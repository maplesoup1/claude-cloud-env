// 章节播放器：一章是一条连续时间轴，镜头表里每一镜是它的一段（做法列写 scenes/cNN.js@起点）。
// 镜头动作按镜头表那一列翻译成 CAM.track 事件：停 / 缓推 / 拉远 / 横移 / 快推 / 砸入 / 切。
(() => {
const { W, H } = NB;
const camFor = (sh) => {
  const cm = sh.cam || {}, f = cm.f || [960, 540], kind = cm.kind || '停';
  let base = { x: 960, y: 540, z: 1 }, ev = [];
  if (cm.base) base = { ...base, ...cm.base };
  if (kind === '缓推') ev = [{ at: cm.at ?? 0.5, kind: 'push', k: cm.k ?? 0.2, x: f[0], y: f[1], dur: cm.dur ?? 1.2 }];
  else if (kind === '拉远') { base = cm.base ? base : { x: f[0], y: f[1], z: cm.z0 ?? 1.35 }; ev = [{ at: cm.at ?? 0.3, kind: 'pull', x: cm.to?.[0] ?? 960, y: cm.to?.[1] ?? 540, z: cm.z1 ?? 1, dur: cm.dur ?? 1.4 }]; }
  else if (kind === '横移') { const a = cm.from || [600, 540], b = cm.to || [1320, 540]; base = { x: a[0], y: a[1], z: cm.z ?? 1.25 }; ev = [{ at: cm.at ?? 0.4, kind: 'glide', x: b[0], y: b[1], dur: cm.dur ?? Math.min(2.2, Math.max(0.8, sh.d - 1.2)) }]; }
  else if (kind === '快推') ev = [{ at: cm.at ?? 0.5, kind: 'punch', k: cm.k ?? 0.26, x: f[0], y: f[1] }];
  else if (kind === '砸入') ev = [{ at: cm.at ?? 0.3, kind: 'slam' }];
  if (cm.extra) ev = ev.concat(cm.extra);
  return { base, ev };
};
window.NBP = {
  draw(c, chap, lt) {
    const shots = window.NBA_SHOTS[chap]; let i = shots.length - 1; while (i > 0 && lt < shots[i].t0 - 1e-6) i--;
    const sh = shots[i], s = lt - sh.t0 + (sh.off || 0); if (!sh._cam) sh._cam = camFor(sh);
    const cam = CAM.track(sh._cam.base, sh._cam.ev, lt - sh.t0);
    c.save(); c.fillStyle = NB.C.bg; c.fillRect(0, 0, W, H);
    c.save(); CAM.apply(c, cam); NBK[sh.k](c, s, sh.p || {}, sh.dfull || sh.d); c.restore();
    NB.finish(c, lt);
    c.restore();
  },
};
})();

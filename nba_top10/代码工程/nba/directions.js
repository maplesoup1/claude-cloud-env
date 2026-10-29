// 三方向硬门：同一个题眼「十个位置、三件已挂的球衣」，三种构图与画法。只用于挑方向，不进成片。
(() => {
const { W, H, F, ZH, rr, ell, text } = NB;
// B：复古印刷海报——米色纸、俯拍平铺，十件球衣摆成两排，大号排名数字压在纸上，网点阴影
NBK.dirB = (c, s) => {
  const P = { bg: '#F3EDE2', ink: '#1B1A17', sub: '#6B655B', acc: '#C8402F', acc2: '#2F5D62' };
  c.fillStyle = P.bg; c.fillRect(-300, -300, W + 600, H + 600);
  const r = U.rng(4); for (let i = 0; i < 4000; i++) { c.fillStyle = `rgba(80,60,40,${r() * 0.06})`; c.fillRect(r() * W, r() * H, 2, 2); }
  text(c, 'ALL-TIME', 120, 170, F(150), P.ink, 'left'); text(c, 'TOP 10', 120, 320, F(150), P.acc, 'left');
  const who = ['curry', 'shaq', 'duncan'];
  for (let k = 0; k < 10; k++) { const x = 760 + (k % 5) * 230, y = 330 + Math.floor(k / 5) * 420;
    text(c, String(10 - k), x - 80, y - 150, F(90), 'rgba(27,26,23,0.18)', 'left');
    if (k < 3) { c.save(); c.translate(x + 60, y + 40); c.rotate((k - 1) * 0.06); c.fillStyle = 'rgba(27,26,23,0.25)'; c.fillRect(-70, -90, 160, 200); NB.jersey(c, 0, 0, 0.55, { ...NB.J[who[k]], col: [P.ink, P.acc, P.acc2][k], trim: P.bg, numCol: P.bg, numStroke: P.ink }, { flat: true }); c.restore(); }
    else { c.strokeStyle = P.sub; c.setLineDash([10, 8]); c.lineWidth = 3; rr(c, x - 20, y - 80, 160, 220, 10); c.stroke(); c.setLineDash([]); } }
  text(c, '谁能挂进这十个位置', 120, 980, ZH(56), P.ink, 'left');
};
// C：粉笔战术板——墨绿黑板，粉笔画的半场和十个圈，三个圈里写了号码，箭头指向下一个
NBK.dirC = (c, s) => {
  const P = { bg: '#23302B', ink: '#F1EFE6', sub: '#A9B3AA', acc: '#F4D35E', acc2: '#E87D5A' };
  c.fillStyle = P.bg; c.fillRect(-300, -300, W + 600, H + 600);
  const r = U.rng(8); for (let i = 0; i < 3000; i++) { c.fillStyle = `rgba(241,239,230,${r() * 0.05})`; c.fillRect(r() * W, r() * H, 3, 1); }
  c.strokeStyle = 'rgba(241,239,230,0.75)'; c.lineWidth = 6; c.lineCap = 'round';
  const wob = (x0, y0, x1, y1) => { c.beginPath(); c.moveTo(x0, y0); c.quadraticCurveTo((x0 + x1) / 2 + 6, (y0 + y1) / 2 - 5, x1, y1); c.stroke(); };
  wob(260, 120, 1660, 120); wob(1660, 120, 1660, 960); wob(260, 960, 1660, 960); wob(260, 120, 260, 960);
  c.beginPath(); c.arc(960, 120, 520, 0.1, Math.PI - 0.1); c.stroke(); c.strokeRect(800, 120, 320, 330);
  const pts = [[420, 300], [560, 560], [760, 760], [960, 820], [1160, 760], [1360, 560], [1500, 300], [960, 560], [700, 420], [1220, 420]];
  pts.forEach(([x, y], k) => { c.strokeStyle = k < 3 ? P.acc : 'rgba(241,239,230,0.6)'; c.lineWidth = 5; ell(c, x, y, 52, 52); c.stroke();
    text(c, k < 3 ? ['30', '34', '21'][k] : String(10 - k), x, y + 20, F(54, 'Kalam-700'), k < 3 ? P.acc : 'rgba(241,239,230,0.6)'); });
  c.strokeStyle = P.acc2; c.lineWidth = 7; c.setLineDash([22, 14]); c.beginPath(); c.moveTo(760, 760); c.quadraticCurveTo(860, 900, 960, 820); c.stroke(); c.setLineDash([]);
  text(c, '前十，怎么排？', 960, 1040, ZH(60, 'Bold'), P.ink);
};
})();

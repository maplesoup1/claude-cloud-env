#!/usr/bin/env python3
"""分镜.py ＋ 口播/行.json → 时间轴。输出：
  代码工程/nba/shots.js、代码工程/eras_nba.js、代码工程/scenes/cNN.js   画面
  章节/NN_*.md                                                    每章镜头表（long_film lint/plan/render 读）
  口播/NN.wav、字幕/NN.srt、字幕/全片.srt                          每章口播与字幕
  总纲.md 的章节表（时长、口播列）
"""
import json, re, sys, wave
from pathlib import Path
import numpy as np, soundfile as sf

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import importlib; 分镜 = importlib.import_module('分镜')

LEAD, GAP, TAIL, FPS = 0.8, 0.45, 1.4, 30
TITLES = {'01': '十个空柜子', '02': '第十个柜子', '03': '两个巨人', '04': '数字与戒指', '05': '八十年代', '06': '山顶', '07': '不锁柜门'}
THREAD = {'01': '一颗旧篮球和十个空柜子', '02': '第十号柜子门口的四件球衣', '03': '34号与21号两件球衣', '04': '一架天平',
          '05': '33号、32号、33号三件球衣', '06': '两件23号球衣', '07': '挂满的十个柜子和那颗旧篮球'}
QUESTION = {'01': '我们用什么尺子量“最伟大”？', '02': '第十名该给科比、大梦、约基奇还是库里？', '03': '巅峰和长度谁更值钱？',
            '04': '数字和戒指，哪个分量更大？', '05': '谁把联盟从低谷里扛了出来？', '06': '乔丹和詹姆斯，谁是第一？', '07': '这张名单会不会有终点？'}
fr = lambda x: round(x * FPS) / FPS

def js_params(p):
    q = {}
    for k, v in p.items():
        if k in ('filled2', 'plates2'): continue
        if k == 'extra_new':
            for r, at in v:
                q.setdefault('filled', p.get('filled', {}))
                q['filled'][r] = {'id': 分镜.NAMES[r], 'at': at}
                q.setdefault('plates', p.get('plates', {}))
                q['plates'][r] = {'text': 分镜.PLATE[分镜.NAMES[r]], 'at': at + 0.9}
            continue
        if k == 'extra_plate':
            r, txt, at = v; q.setdefault('plates', p.get('plates', {})); q['plates'][r] = {'text': txt, 'at': at}; continue
        q[k[:-1] if k.endswith('_') else k] = v
    for k in ('filled', 'plates'):
        if k in p and k not in q: q[k] = p[k]
    return q

def cam_params(kind, cp):
    c = {'kind': kind}
    for k, v in cp.items():
        c['from' if k == 'frm' else k] = v
    return c

lines = json.loads((ROOT / '口播/行.json').read_text())
shots_js, eras, srt_all, outline_rows = {}, [], [], []
film_t = 0.0
for ch in sorted(分镜.S):
    spec, L = 分镜.S[ch], lines[ch]
    assert len(spec) == len(L), f'{ch}: 分镜 {len(spec)} 条，口播 {len(L)} 句'
    t, shots, subs = 0.0, [], []
    for i, (sp, ln) in enumerate(zip(spec, L)):
        start = LEAD if i == 0 else t          # 这一句开始说的时刻
        slot = ln['dur'] + GAP + (LEAD if i == 0 else 0) + (TAIL if i == len(L) - 1 else 0)
        subs.append((start, start + ln['dur'], ln['text'].replace('M V P', 'MVP').replace('N B A', 'NBA'), ln['wav']))
        if sp == '+':
            shots[-1]['d'] += slot
        else:
            group = sp if isinstance(sp, list) else [sp]
            ws = [g['w'] for g in group]; acc = t
            for g, w in zip(group, ws):
                d = slot * w / sum(ws)
                shots.append({'t0': acc, 'd': d, 'k': g['k'], 'p': js_params(g['p']), 'cam': cam_params(g['cam'], g['cp']),
                              'obj': g['obj'], 'verb': g['verb'], 'txt': g['txt'], 'camz': g['cam']})
                acc += d
        t += slot
    # 超过 6 秒的镜拆成两镜：同一个画面接着演（off = 时间接续），后半镜换景别（推过的拉回来；没推的跳近一档）
    out = []
    for s_ in shots:
        if s_['d'] <= 6.0:
            out.append(s_); continue
        d1 = s_['d'] * 0.55; a = dict(s_, d=d1, dfull=s_['d']); b = dict(s_, t0=s_['t0'] + d1, d=s_['d'] - d1, off=d1, txt='', dfull=s_['d'])
        f = s_['cam'].get('f') or s_['cam'].get('to') or [960, 540]
        if s_['camz'] in ('缓推', '快推'):
            b['cam'] = {'kind': '拉远', 'f': f, 'z0': 1.3, 'z1': 1.0, 'to': [960, 540], 'at': 0.2, 'dur': 1.4}; b['camz'] = '拉远'
        else:
            b['cam'] = {'kind': '切', 'base': {'x': (f[0] + 960) / 2, 'y': (f[1] + 540) / 2, 'z': 1.28}}; b['camz'] = '切'
        out += [a, b]
    shots = out
    shots[0]['txt'] = ''
    # 对齐到帧
    total = fr(t); e = 0.0
    for k, s in enumerate(shots):
        s0 = fr(s['t0']); s1 = fr(s['t0'] + s['d']) if k < len(shots) - 1 else total
        s['t0'], s['d'] = s0, round(s1 - s0, 4)
    shots_js[ch] = [{k: s[k] for k in ('t0', 'd', 'k', 'p', 'cam', 'off', 'dfull') if k in s} for s in shots]
    eras.append({'id': f'c{ch}', 'dur': total})
    # 镜头表
    title = TITLES[ch]
    md = [f'# 第{ch}章 {title}', '', f'这一章的问题：{QUESTION[ch]}  贯穿物：{THREAD[ch]}', '',
          '章内时间从 0 开始。画风锁继承总纲。时间段按口播实际时长排（build.py 生成，不要手改；改 分镜.py 后重跑）。', '',
          '| 时间段 | 画面里的物 | 它在做什么 | 镜头 | 屏上字 | 做法 |', '|---|---|---|---|---|---|']
    for s in shots:
        md.append(f"| {s['t0']:.2f}–{s['t0'] + s['d']:.2f} | {s['obj']} | {s['verb']} | {s['camz']} | {s['txt']} | scenes/c{ch}.js@{s['t0']:.2f} |")
    for old in (ROOT / '章节').glob(f'{ch}_*.md'): old.unlink()
    (ROOT / '章节' / f'{ch}_{title}.md').write_text('\n'.join(md) + '\n')
    # 口播（24kHz 单声道）
    sr = 24000; buf = np.zeros(int(round(total * sr)) + 1, dtype=np.float32)
    for a, b, txt, wav in subs:
        x, r = sf.read(wav, dtype='float32'); assert r == sr
        i0 = int(round(a * sr)); buf[i0:i0 + len(x)] += x[:len(buf) - i0]
    (ROOT / '口播').mkdir(exist_ok=True); sf.write(ROOT / '口播' / f'{ch}.wav', buf, sr)
    # 字幕
    def ts(x): h, r = divmod(x, 3600); m, s_ = divmod(r, 60); return f'{int(h):02d}:{int(m):02d}:{int(s_):02d},{int(round((s_ % 1) * 1000)) % 1000:03d}'
    (ROOT / '字幕').mkdir(exist_ok=True)
    (ROOT / '字幕' / f'{ch}.srt').write_text('\n'.join(f'{k + 1}\n{ts(a)} --> {ts(b)}\n{txt}\n' for k, (a, b, txt, _) in enumerate(subs)))
    srt_all += [(film_t + a, film_t + b, txt) for a, b, txt, _ in subs]
    outline_rows.append((ch, title, total, f'章节/{ch}_{title}.md', f'口播/{ch}.wav', f'文稿/{ch}.txt', THREAD[ch], QUESTION[ch]))
    durs = [s['d'] for s in shots]
    print(f'{ch} {title}: {len(shots)} 镜, {total:.1f}s, 镜长 {min(durs):.2f}–{max(durs):.2f}, >6.5s: {sum(d > 6.5 for d in durs)}, <2s: {sum(d < 2 for d in durs)}')
    film_t += total

E = ROOT / '代码工程'
(E / 'nba' / 'shots.js').write_text('// build.py 生成，勿手改\nwindow.NBA_SHOTS = ' + json.dumps(shots_js, ensure_ascii=False) + ';\n')
(E / 'eras_nba.js').write_text("// NBA 历史前十：每章一段，画面由 nba/*.js 按 shots.js 的时间轴画（build.py 生成）\n"
    "window.SCENE_LIBS = ['nba/core.js', 'nba/kinds.js', 'nba/player.js', 'nba/shots.js'];\nwindow.PUNCH = 0;\n"
    "window.ERAS = [\n" + ''.join(f"  {{ id: '{e['id']}', dur: {e['dur']} }},\n" for e in eras) + "];\n")
for e in eras:
    (E / 'scenes' / f"{e['id']}.js").write_text(f"SCENES['{e['id']}'] = {{ draw: (c, lt) => NBP.draw(c, '{e['id'][1:]}', lt) }};\n")
def ts(x): h, r = divmod(x, 3600); m, s_ = divmod(r, 60); return f'{int(h):02d}:{int(m):02d}:{int(s_):02d},{int(round((s_ % 1) * 1000)) % 1000:03d}'
(ROOT / '字幕' / '全片.srt').write_text('\n'.join(f'{k + 1}\n{ts(a)} --> {ts(b)}\n{txt}\n' for k, (a, b, txt) in enumerate(srt_all)))
# 总纲章节表
o = (ROOT / '总纲.md').read_text()
tbl = ['| 章 | 标题 | 时长 | 镜头表 | 口播 | 文稿 | 贯穿物 | 这一章的问题 |', '|---|---|---|---|---|---|---|---|']
for ch, title, d, f, a, s, th, q in outline_rows:
    tbl.append(f'| {ch} | {title} | {int(d // 60)}:{d % 60:04.1f} | {f} | {a} | {s} | {th} | {q} |')
o = re.sub(r'\| 章 \|.*?(?=\n\n|\Z)', '\n'.join(tbl), o, flags=re.S)
(ROOT / '总纲.md').write_text(o)
print(f'全片 {film_t:.1f}s = {int(film_t // 60)}:{film_t % 60:04.1f}')

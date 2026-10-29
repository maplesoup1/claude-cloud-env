#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""long_film.py —— 10–30 分钟长片的总控：总纲 → 分章镜头表 → 并行逐镜渲染（断点续渲）→ 拼章 → 拼整片带章节 → 分段门禁 → 交付。

一支 20 分钟的片子是 300–400 镜、3.6 万帧（30fps）。单进程逐帧渲要好几个小时，中途一崩全部重来；
整片一张镜头表几百行，lint 和人都看不过来。这个脚本把它拆成「章」，每章一张普通镜头表（storyboard_lint 照查），
每一镜单独出一个 mp4（渲完才落盘，已经渲好的跳过），最后拼起来。方法论见 references/17-长片.md。

用法（<项目> 是项目目录）：
  python3 long_film.py init     <项目> [--minutes 20] [--chapters 7]    # 搭骨架：总纲.md、章节/*.md、代码工程/
  python3 long_film.py lint     <项目> [--script-dir 文稿/]              # 每章跑 storyboard_lint ＋ 跨章检查；红灯非零退出
  python3 long_film.py plan     <项目>                                   # 每一镜怎么出：spec / scenes / 素材，缺什么，估渲染时间
  python3 long_film.py render   <项目> [-j 4] [--chapter 03] [--force] [--png] [--dry-run]
  python3 long_film.py status   <项目>                                   # 渲了多少、还差哪些、按实测速度估还要多久
  python3 long_film.py assemble <项目> [--audio 口播.wav] [--music 配乐.wav --music-db -18] [--crf 16]
  python3 long_film.py gate     <项目> [-j 4]                            # film_gate 分章量（每章都要过快动红线）
  python3 long_film.py deliver  <项目> [--allow-blue-purple 理由]        # deliver.py ＋ 章节表

项目目录约定：
  总纲.md              片名、目标时长、画幅、画风锁三行（画风/色板/角色，各章继承）、章节表
  章节/<章>.md         每章一张镜头表，时间段从 0 开始（章内时间）；表前不必再写画风锁，写了就必须和总纲一致
  代码工程/            scripts/engine 的拷贝（init 会复制）；scenes/<id>.js 要登记进 eras.js（或 --film 指定的 eras_<名>.js）
  片段/                参数化片段 spec（做法列写 镜NN.json 时，先找章节文件旁边，再找 片段/、片段/<章>/、项目根）
  素材/                实拍、录屏（做法列写 素材 xxx.mp4 时会被规范成统一画幅、帧率、时长）
  镜/<章>/镜NN.mp4     渲染结果（素材镜也可以直接把成品放这里，plan 会认）
  章/<章>.mp4          assemble 拼好的章
  成片.mp4 章节.json 章节.txt   assemble 输出；章节.txt 是 YouTube 简介里能直接贴的章节时间码

做法列怎么写才能自动渲：
  y2 片段 镜03.json              参数化片段（render.py --spec）；spec 的 duration、宽高、fps 要和镜头表、总纲一致
  scenes/kitchen.js              代码场景（render.py --solo kitchen --from 0 --to <镜长>）
  scenes/kitchen.js@12.5         同一个场景的第 12.5 秒起（一个场景跨几镜时，每镜接着上一镜的时间往下走）
  素材 素材/采访.mp4@30          实拍/录屏从第 30 秒起截镜长那么长，缩放补边到统一画幅
  其它（素材 照片满幅…）          自动渲不了：把做好的 镜NN.mp4 放进 镜/<章>/，或改成 spec 用 MD.cover 放图

渲染 Python：默认当前解释器能 import playwright 就用它，否则 `uv run -q --with playwright python`；
环境变量 LONG_FILM_PYTHON 可以整条覆盖（例如 "uv run -q --with playwright==1.63.0 python"）。
Playwright 版本和本机浏览器对不上时，render.py 会退回用本机已有的 Chromium（engine/launch.py）。
只用标准库；ffmpeg/ffprobe 要在 PATH 上。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(HERE))
import storyboard_lint as SL  # noqa: E402

RED, YELLOW, GREEN = SL.RED, SL.YELLOW, SL.GREEN
OUTLINE = "总纲.md"
LOCK_KEYS = ("画风", "色板", "角色", "允许蓝紫")
META = re.compile(r"^\s*(片名|目标时长|画幅|场景表)\s*[:：]\s*(.+?)\s*$")


# ---------------------------------------------------------------- 读总纲
def parse_t(cell):
    """1:30 / 90 / 1:30:00 / 20分 / 20min → 秒。"""
    c = SL.clean_cell(cell)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(分钟|分|min)", c)
    if m:
        return float(m.group(1)) * 60
    m = re.search(r"\d+(?::\d+){0,2}(?:\.\d+)?", c)
    if not m:
        return None
    parts = [float(x) for x in m.group(0).split(":")]
    v = 0.0
    for x in parts:
        v = v * 60 + x
    return v


def fmt(sec):
    sec = max(0.0, float(sec))
    h, rem = divmod(int(round(sec)), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def read_outline(proj: Path):
    p = proj / OUTLINE
    if not p.is_file():
        raise SystemExit(f"找不到 {p}。先跑：python3 {Path(__file__).name} init {proj}")
    text = p.read_text(encoding="utf-8")
    meta, fence = {}, False
    for ln in text.splitlines():
        if ln.strip().startswith("```"):
            fence = not fence; continue
        m = None if fence else META.match(ln)
        if m:
            meta.setdefault(m.group(1), m.group(2))
    lock = SL.read_lock(text)
    head, rows = find_chapter_table(text)
    if head is None:
        raise SystemExit(f"{p} 里找不到章节表：表头要有「章」「时长」「镜头表」三列（见 references/17-长片.md）")
    col = {}
    for k, h in enumerate(head):
        if "镜头表" in h or "文件" in h: col.setdefault("file", k)
        elif "标题" in h or "名" in h: col.setdefault("title", k)
        elif "时长" in h: col.setdefault("dur", k)
        elif "口播" in h or "音频" in h: col.setdefault("audio", k)
        elif "文稿" in h: col.setdefault("script", k)
        elif "贯穿" in h or "例子" in h: col.setdefault("thread", k)
        elif "章" in h: col.setdefault("id", k)
    get = lambda cells, k: SL.clean_cell(cells[col[k]]) if k in col and col[k] < len(cells) else ""
    chapters = []
    for lineno, cells in rows:
        if all(SL.is_empty(c) for c in cells):
            continue
        cid = get(cells, "id") or f"{len(chapters) + 1:02d}"
        f = get(cells, "file")
        chapters.append({
            "id": re.sub(r"[\\/:*?\"<>|\s]+", "_", cid), "title": get(cells, "title") or cid, "line": lineno,
            "planned": parse_t(get(cells, "dur")), "file": (proj / f) if f and not SL.is_empty(f) else None,
            "audio": (proj / get(cells, "audio")) if get(cells, "audio") and not SL.is_empty(get(cells, "audio")) else None,
            "script": (proj / get(cells, "script")) if get(cells, "script") and not SL.is_empty(get(cells, "script")) else None,
            "thread": get(cells, "thread"),
        })
    size = (1920, 1080, 30)
    if meta.get("画幅"):
        m = re.search(r"(\d+)\s*[x×*]\s*(\d+)(?:\s*@\s*(\d+))?", meta["画幅"])
        if m:
            size = (int(m.group(1)), int(m.group(2)), int(m.group(3) or 30))
    return {"path": p, "text": text, "meta": meta, "lock": lock, "chapters": chapters, "size": size,
            "target": parse_t(meta.get("目标时长", "")) if meta.get("目标时长") else None,
            "film": (meta.get("场景表") or "").strip()}


def find_chapter_table(text):
    lines, fence, i = text.splitlines(), False, 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            fence = not fence; i += 1; continue
        if not fence and ln.strip().startswith(("|", "｜")) and i + 1 < len(lines) and re.match(r"^\s*[|｜]?\s*:?-{2,}", lines[i + 1]):
            head = SL.strip_cells(ln)
            rows, j = [], i + 2
            while j < len(lines) and lines[j].strip().startswith(("|", "｜")):
                rows.append((j + 1, SL.strip_cells(lines[j]))); j += 1
            if any("章" in h for h in head) and any("镜头表" in h or "文件" in h for h in head):
                return head, rows
            i = j; continue
        i += 1
    return None, []


def chapter_text(outline, ch):
    """章节镜头表全文；表前没写画风锁的项从总纲继承（写在最前面，章节自己写的离表更近、优先）。"""
    text = ch["file"].read_text(encoding="utf-8")
    inherit = "".join(f"{k}：{v}\n" for k, v in outline["lock"].items() if k in LOCK_KEYS)
    return inherit + "\n" + text, SL.read_lock(text)


# ---------------------------------------------------------------- lint
def cmd_lint(a):
    proj = Path(a.project).resolve()
    O = read_outline(proj)
    film_issues, chapter_res, total, any_red = [], [], 0.0, False
    add = lambda lv, tag, what, fix: film_issues.append((lv, tag, what, fix))
    miss = [k for k in ("画风", "色板", "角色") if not O["lock"].get(k)]
    if miss:
        add(RED, "画风锁", f"总纲缺「{'」「'.join(miss)}」", "总纲表前写三行，全片各章继承；20 分钟里换画风就是 20 分钟的拼贴")
    if not O["chapters"]:
        add(RED, "章节", "章节表是空的", "一行一章：章｜标题｜时长｜镜头表｜贯穿物")
    grams_by_ch, kinds_by_ch = {}, {}
    script_dir = Path(a.script_dir).resolve() if a.script_dir else None
    for ch in O["chapters"]:
        tag = f"第{ch['id']}章"
        if ch["file"] is None or not ch["file"].is_file():
            add(RED, tag, f"镜头表文件不存在：{ch['file']}", "在章节表的「镜头表」列写对路径，或先跑 init")
            continue
        text, own = chapter_text(O, ch)
        for k in ("画风", "色板", "角色"):
            if own.get(k) and O["lock"].get(k) and own[k] != O["lock"][k]:
                add(RED, tag, f"这一章自己写了「{k}：{own[k]}」，和总纲（{O['lock'][k]}）不一样",
                    "章节不换画风锁：删掉章节里的这一行（继承总纲），或者改总纲让全片一起换")
        script = None
        sp = ch["script"] or (script_dir / f"{ch['id']}.txt" if script_dir else None)
        if sp and sp.is_file():
            script = sp.read_text(encoding="utf-8")
        res = SL.lint(text, script)
        chapter_res.append((ch, res))
        if "error" in res:
            add(RED, tag, res["error"], "按 references/镜头表模板.md 写这一章的表")
            continue
        any_red |= res["verdict"] == RED
        total += res["total"]
        if ch["planned"] and abs(res["total"] - ch["planned"]) > max(5.0, 0.08 * ch["planned"]):
            add(YELLOW, tag, f"镜头表合计 {fmt(res['total'])}，总纲写的是 {fmt(ch['planned'])}",
                "改总纲的时长，或增删镜头；有口播时以口播实际时长为准")
        if res["total"] > 300:
            add(YELLOW, tag, f"这一章 {fmt(res['total'])}，超过 5 分钟", "长于 5 分钟的章观众会走神：拆成两章，中间换一次节拍（换语法、换景、换贯穿物的状态）")
        if res["total"] < 45 and len(O["chapters"]) > 1:
            add(YELLOW, tag, f"这一章只有 {fmt(res['total'])}", "短于 45 秒的章撑不起一个段落，并到前后章里")
        rows = res["rows"]
        grams_by_ch[ch["id"]] = sorted({k for k in (SL.how_kind(r["how"]) for r in rows) if k and SL.GRAMMAR.fullmatch(k)})
        kinds = [SL.how_kind(r["how"]) for r in rows if SL.how_kind(r["how"])]
        kinds_by_ch[ch["id"]] = max(set(kinds), key=kinds.count) if kinds else None
    # 跨章
    allg = sorted({g for gs in grams_by_ch.values() for g in gs})
    if len(allg) > 4:
        add(RED, "全片", f"全片用了 {len(allg)} 种片段语法（{'、'.join(allg)}）",
            "长片最多 4 种、每章最多 2 种，所有 spec 同一个 theme；换语法是换节拍，不是换画风")
    ids = list(kinds_by_ch)
    for k in range(2, len(ids)):
        a3 = [kinds_by_ch[i] for i in ids[k - 2:k + 1]]
        if a3[0] and a3[0] == a3[1] == a3[2]:
            add(YELLOW, "节拍", f"第{ids[k - 2]}–{ids[k]}章连续三章主做法都是「{a3[0]}」",
                "长片的疲劳来自同一种节拍反复：中间那章换主做法（片段语法↔scenes↔真实素材），或换景别和镜头基调")
    threads = [ch["thread"] for ch in O["chapters"]]
    if O["chapters"] and not any(threads):
        add(YELLOW, "贯穿", "章节表没有「贯穿物」列", "每章写一个贯穿这一章的具体例子；全片再有一个从头走到尾的母题（references/17-长片.md）")
    if O["target"] and total and abs(total - O["target"]) > 0.1 * O["target"]:
        add(YELLOW, "全片", f"各章合计 {fmt(total)}，目标 {fmt(O['target'])}", "增删章节或镜头；口播定稿后以口播为准")
    for ch, res in chapter_res:
        print(f"\n━━ 第{ch['id']}章 {ch['title']}（{ch['file'].relative_to(proj) if ch['file'] else '?'}）")
        print("\n".join("  " + ln for ln in SL.report(res)[:-1]))
    print(f"\n━━ 全片：{len(O['chapters'])} 章，{sum(len(r.get('rows', [])) for _, r in chapter_res)} 镜，{fmt(total)}"
          + (f"（目标 {fmt(O['target'])}）" if O["target"] else ""))
    for lv, tag, what, fix in film_issues:
        print(f"  [{lv}] {tag}：{what}。改：{fix}")
    any_red |= any(x[0] == RED for x in film_issues)
    yellow = any(x[0] == YELLOW for x in film_issues) or any(r.get("verdict") == YELLOW for _, r in chapter_res)
    print("\n结论：" + ("红灯。先改，红灯清掉之前不要开始渲染。" if any_red else
                       "黄灯。可以开始做；黄灯项想清楚理由。" if yellow else "绿灯。可以开始做。"))
    print("机器查不了、要你自己对的：每章是不是一个具体例子贯穿；章与章之间有没有一个全片母题接着走；每章开头是不是一个小场景、结尾是不是一个动作。")
    return 1 if any_red else 0


# ---------------------------------------------------------------- plan
SCENE_RE = re.compile(r"scenes/([\w\-一-鿿]+)\.js(?:\s*@\s*(\d+(?:\.\d+)?))?")
VIDEO_RE = re.compile(r"([^\s|，,：:（）()]+\.(?:mp4|mov|mkv|webm|m4v))(?:\s*@\s*(\d+(?:\.\d+)?))?", re.I)


def find_file(name, proj, ch):
    cands = [ch["file"].parent / name, proj / "片段" / ch["id"] / name, proj / "片段" / name, proj / name]
    return next((c.resolve() for c in cands if c.is_file()), None)


def engine_dir(proj):
    return proj / "代码工程"


def registered_ids(proj, film):
    f = engine_dir(proj) / (f"eras_{film}.js" if film else "eras.js")
    if not f.is_file():
        return None
    return set(re.findall(r"\bid\s*:\s*['\"]([^'\"]+)['\"]", f.read_text(encoding="utf-8")))


def build_plan(proj, O):
    W, H, FPS = O["size"]
    ids = registered_ids(proj, O["film"])
    jobs = []
    for ch in O["chapters"]:
        if ch["file"] is None or not ch["file"].is_file():
            continue
        res = SL.lint(chapter_text(O, ch)[0])
        if "error" in res:
            continue
        for r in res["rows"]:
            n = r["n"]
            out = proj / "镜" / ch["id"] / f"镜{n:02d}.mp4"
            j = {"chapter": ch["id"], "n": n, "out": str(out), "dur": r["dur"] or 0, "how": r["how"], "obj": r["obj"],
                 "span": r["span"], "kind": None, "problem": None}
            how = r["how"]
            clip = SL.clip_name(how)
            sc = SCENE_RE.search(how)
            vid = VIDEO_RE.search(how)
            if clip:
                f = find_file(clip, proj, ch)
                j["kind"] = "spec"
                if not f:
                    j["problem"] = f"找不到 {clip}（找过章节旁、片段/{ch['id']}/、片段/、项目根）"
                else:
                    j["src"] = str(f)
                    try:
                        sp = json.loads(f.read_text(encoding="utf-8"))
                        d = float(sp.get("duration", 0))
                        if abs(d - j["dur"]) > 1.0 / FPS + 1e-6:
                            j["problem"] = f"{clip} 的 duration={d:g}，镜头表这一镜 {j['dur']:g} 秒"
                        elif (sp.get("width", 1920), sp.get("height", 1080), sp.get("fps", 30)) != (W, H, FPS):
                            j["problem"] = (f"{clip} 是 {sp.get('width', 1920)}×{sp.get('height', 1080)}@{sp.get('fps', 30)}，"
                                            f"总纲画幅 {W}×{H}@{FPS}")
                    except (ValueError, OSError) as e:
                        j["problem"] = f"{clip} 读不了：{e}"
            elif sc:
                sid, st = sc.group(1), float(sc.group(2) or 0)
                j.update(kind="scene", scene=sid, start=st)
                sf = engine_dir(proj) / "scenes" / f"{sid}.js"
                if not sf.is_file():
                    j["problem"] = f"代码工程/scenes/{sid}.js 不存在"
                elif ids is not None and sid not in ids:
                    j["problem"] = f"{sid} 没登记进 {'eras_' + O['film'] + '.js' if O['film'] else 'eras.js'}（render.py --solo 找不到它）"
                else:
                    j["src"] = str(sf)
            elif vid and (find_file(vid.group(1), proj, ch) or (proj / "素材" / vid.group(1)).is_file()):
                f = find_file(vid.group(1), proj, ch) or (proj / "素材" / vid.group(1)).resolve()
                j.update(kind="footage", src=str(f), start=float(vid.group(2) or 0))
            else:
                j["kind"] = "manual"
                if not out.is_file():
                    j["problem"] = f"做法「{how or '（空）'}」自动渲不了：把成品放到 镜/{ch['id']}/镜{n:02d}.mp4，或改成 spec / scenes"
            jobs.append(j)
    return jobs


def inputs_mtime(j, proj, O):
    files = [j.get("src")]
    if j["kind"] in ("scene", "spec"):
        e = engine_dir(proj)
        files += [e / (f"eras_{O['film']}.js" if O["film"] else "eras.js"), e / "engine.js"]
    return max((Path(f).stat().st_mtime for f in files if f and Path(f).is_file()), default=0)


def signature(j, O):
    """这一镜是怎么出的：做法、源文件、起点、镜长、画幅。改了任何一样（换做法、改镜长）都要重渲，光看文件时间看不出来。"""
    return {"kind": j["kind"], "src": j.get("src"), "scene": j.get("scene"), "start": j.get("start"), "dur": j["dur"],
            "size": list(O["size"]), "film": O["film"]}


def sig_path(out):
    return Path(out).with_suffix(".json")


def is_fresh(j, proj, O):
    out = Path(j["out"])
    if not out.is_file():
        return False
    if j["kind"] == "manual":
        return True
    try:
        if json.loads(sig_path(out).read_text()) != signature(j, O):
            return False
    except (OSError, ValueError):
        return False
    return out.stat().st_mtime >= inputs_mtime(j, proj, O)


def speed_log(proj):
    f = proj / "渲染" / "速度.json"
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return {}


def estimate(jobs, proj, O, jn):
    """按实测秒/帧（渲染/速度.json，按做法种类记）估剩余时间；没有实测时按 0.25 秒/帧（JPEG 传帧、中等复杂度场景）。"""
    sp = speed_log(proj)
    FPS = O["size"][2]
    tot = 0.0
    for j in jobs:
        key = j.get("scene") or j["kind"]
        tot += j["dur"] * FPS * sp.get(key, sp.get(j["kind"], 0.25 if j["kind"] != "footage" else 0.01))
    return tot / max(1, jn)


def cmd_plan(a):
    proj = Path(a.project).resolve()
    O = read_outline(proj)
    jobs = build_plan(proj, O)
    W, H, FPS = O["size"]
    by = {}
    for j in jobs:
        by.setdefault(j["chapter"], []).append(j)
    todo = [j for j in jobs if not is_fresh(j, proj, O) and j["kind"] != "manual"]
    probs = [j for j in jobs if j["problem"]]
    for cid, js in by.items():
        print(f"━━ 第{cid}章：{len(js)} 镜，{fmt(sum(j['dur'] for j in js))}")
        for j in js:
            st = "✓ 已渲" if is_fresh(j, proj, O) else ("✗ " + j["problem"]) if j["problem"] else "· 待渲"
            extra = f" {j['scene']}@{j['start']:g}" if j["kind"] == "scene" else ""
            print(f"  镜{j['n']:02d} {j['dur']:>4g}s  {j['kind']:<7}{extra:<18} {st}")
    (proj / "渲染").mkdir(exist_ok=True)
    (proj / "渲染" / "计划.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=1))
    frames = sum(round(j["dur"] * FPS) for j in todo)
    jn = a.jobs or os.cpu_count() or 2
    print(f"\n全片 {len(jobs)} 镜，{fmt(sum(j['dur'] for j in jobs))}，{W}×{H}@{FPS}；待渲 {len(todo)} 镜 {frames} 帧；"
          f"有问题 {len(probs)} 镜。按 {jn} 路并行估约 {fmt(estimate(todo, proj, O, jn))}（实测速度见 渲染/速度.json，渲过之后更准）")
    return 1 if probs else 0


# ---------------------------------------------------------------- render
def render_python():
    env = os.environ.get("LONG_FILM_PYTHON")
    if env:
        return shlex.split(env)
    try:
        subprocess.run([sys.executable, "-c", "import playwright"], check=True, capture_output=True)
        return [sys.executable]
    except subprocess.CalledProcessError:
        return ["uv", "run", "-q", "--with", "playwright", "python"]


def probe_frames(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                          "-show_entries", "stream=nb_read_packets,width,height,r_frame_rate", "-of", "json", str(path)],
                         capture_output=True, text=True)
    if out.returncode:
        return None
    s = json.loads(out.stdout)["streams"][0]
    num, _, den = s["r_frame_rate"].partition("/")
    return {"frames": int(s.get("nb_read_packets", 0)), "w": s["width"], "h": s["height"], "fps": float(num) / float(den or 1)}


def job_cmd(j, proj, O, a, tmp):
    W, H, FPS = O["size"]
    eng = engine_dir(proj)
    py = render_python()
    jpeg = [] if a.png else ["--jpeg"]
    if j["kind"] == "spec":
        return py + [str(eng / "render.py"), "--spec", j["src"], "--out", str(tmp)] + jpeg
    if j["kind"] == "scene":
        return py + [str(eng / "render.py"), "--solo", j["scene"], "--from", f"{j['start']:g}", "--to", f"{j['start'] + j['dur']:g}",
                     "--fps", str(FPS), "--no-counter", "--width", str(W), "--height", str(H), "--out", str(tmp)] + \
            (["--film", O["film"]] if O["film"] else []) + jpeg
    if j["kind"] == "footage":
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},setsar=1")
        return ["ffmpeg", "-y", "-v", "error", "-ss", f"{j['start']:g}", "-i", j["src"], "-t", f"{j['dur']:g}", "-vf", vf, "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-frames:v", str(round(j["dur"] * FPS)), str(tmp)]
    raise ValueError(j["kind"])


def run_job(j, proj, O, a):
    out = Path(j["out"]); out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.mp4")
    log = proj / "渲染" / "日志" / f"{j['chapter']}_镜{j['n']:02d}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = job_cmd(j, proj, O, a, tmp)
    want = round(j["dur"] * O["size"][2])
    err = None
    for attempt in (1, 2):   # 一次重试：Chromium 偶尔起不来；第二次还失败就是真的错
        t0 = time.time()
        with open(log, "w", encoding="utf-8") as lf:
            lf.write("$ " + " ".join(shlex.quote(str(c)) for c in cmd) + "\n")
            lf.flush()
            r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=str(engine_dir(proj)) if engine_dir(proj).is_dir() else None)
        el = time.time() - t0
        if r.returncode == 0 and tmp.is_file():
            pf = probe_frames(tmp)
            if pf and abs(pf["frames"] - want) <= 1 and (pf["w"], pf["h"]) == O["size"][:2]:
                os.replace(tmp, out)
                sig_path(out).write_text(json.dumps(signature(j, O), ensure_ascii=False))
                return j, None, el / max(1, want)
            err = f"出来的片子不对：{pf}，应为 {want} 帧 {O['size'][0]}×{O['size'][1]}"
        else:
            err = f"退出码 {r.returncode}"
        if tmp.exists():
            tmp.unlink()
    return j, f"{err}（日志 {log.relative_to(proj)}）", None


def cmd_render(a):
    proj = Path(a.project).resolve()
    O = read_outline(proj)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("需要 ffmpeg/ffprobe")
    if not (engine_dir(proj) / "render.py").is_file():
        raise SystemExit(f"{engine_dir(proj)} 里没有 render.py：先跑 init，或把 scripts/engine 复制过去")
    jobs = build_plan(proj, O)
    if a.chapter:
        keep = set(a.chapter)
        jobs = [j for j in jobs if j["chapter"] in keep]
    probs = [j for j in jobs if j["problem"]]
    for j in probs:
        print(f"✗ 第{j['chapter']}章 镜{j['n']:02d}：{j['problem']}")
    todo = [j for j in jobs if not j["problem"] and j["kind"] != "manual" and (a.force or not is_fresh(j, proj, O))]
    # 长的先渲，并行时尾巴短
    todo.sort(key=lambda j: -j["dur"])
    jn = max(1, a.jobs or os.cpu_count() or 2)
    print(f"待渲 {len(todo)} 镜（跳过已渲 {sum(1 for j in jobs if is_fresh(j, proj, O) and j['kind'] != 'manual') if not a.force else 0}），"
          f"{jn} 路并行，估约 {fmt(estimate(todo, proj, O, jn))}")
    if a.dry_run:
        for j in todo:
            print("  " + " ".join(shlex.quote(str(c)) for c in job_cmd(j, proj, O, a, Path(j['out']).with_suffix('.part.mp4'))))
        return 0
    sp = speed_log(proj)
    done = failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(jn) as ex:
        futs = [ex.submit(run_job, j, proj, O, a) for j in todo]
        for f in as_completed(futs):
            j, err, spf = f.result()
            if err:
                failed += 1
                print(f"✗ 第{j['chapter']}章 镜{j['n']:02d}：{err}", flush=True)
            else:
                done += 1
                key = j.get("scene") or j["kind"]
                sp[key] = round(spf, 4)   # 单路在并行负载下的秒/帧；估时间时再除以路数
                print(f"✓ 第{j['chapter']}章 镜{j['n']:02d}（{j['dur']:g}s）[{done + failed}/{len(todo)}，已用 {fmt(time.time() - t0)}]", flush=True)
    (proj / "渲染").mkdir(exist_ok=True)
    (proj / "渲染" / "速度.json").write_text(json.dumps(sp, ensure_ascii=False, indent=1))
    print(f"\n渲完 {done} 镜，失败 {failed} 镜，有问题没渲 {len(probs)} 镜，用时 {fmt(time.time() - t0)}。"
          + ("再跑一次 render 只补没渲好的。" if failed or probs else "下一步：assemble。"))
    return 1 if failed or probs else 0


def cmd_status(a):
    proj = Path(a.project).resolve()
    O = read_outline(proj)
    jobs = build_plan(proj, O)
    FPS = O["size"][2]
    fresh = [j for j in jobs if is_fresh(j, proj, O)]
    stale = [j for j in jobs if Path(j["out"]).is_file() and not is_fresh(j, proj, O)]
    left = [j for j in jobs if not is_fresh(j, proj, O)]
    by = {}
    for j in jobs:
        d = by.setdefault(j["chapter"], [0, 0, 0.0])
        d[0] += 1; d[1] += is_fresh(j, proj, O); d[2] += j["dur"]
    for cid, (n, ok, dur) in by.items():
        bar = "█" * round(20 * ok / max(1, n)) + "░" * (20 - round(20 * ok / max(1, n)))
        ch_out = proj / "章" / f"{cid}.mp4"
        print(f"第{cid}章 {bar} {ok}/{n} 镜  {fmt(dur)}" + ("  章已拼" if ch_out.is_file() else ""))
    jn = a.jobs or os.cpu_count() or 2
    print(f"\n已渲 {len(fresh)}/{len(jobs)} 镜（{fmt(sum(j['dur'] for j in fresh))}/{fmt(sum(j['dur'] for j in jobs))}）；"
          f"过期（源文件在渲染之后改过）{len(stale)} 镜；剩 {sum(round(j['dur'] * FPS) for j in left)} 帧，"
          f"{jn} 路并行估约 {fmt(estimate([j for j in left if j['kind'] != 'manual'], proj, O, jn))}")
    probs = [j for j in jobs if j["problem"]]
    if probs:
        print(f"有问题 {len(probs)} 镜（plan 看详情）")
    return 0


# ---------------------------------------------------------------- assemble
def ff(cmd):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error"] + cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("ffmpeg 失败：\n" + " ".join(shlex.quote(c) for c in cmd) + "\n" + r.stderr[-2000:])


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], text=True)
    return float(out.strip() or 0)


def assemble_chapter(ch, shots, proj, O, a):
    """一章：镜按顺序重编码拼接（各镜来自不同编码设置，直接 -c copy 容易花屏）；有本章口播就混进来，没有就补静音轨。"""
    W, H, FPS = O["size"]
    out = proj / "章" / f"{ch['id']}.mp4"
    out.parent.mkdir(exist_ok=True)
    lst = proj / "渲染" / f"拼接_{ch['id']}.txt"
    lst.write_text("".join(f"file '{Path(s).resolve().as_posix()}'\n" for s in shots))
    vdur = sum(round(duration(s) * FPS) for s in shots) / FPS
    audio = ch["audio"] if ch["audio"] and ch["audio"].is_file() else None
    cmd = ["-f", "concat", "-safe", "0", "-i", str(lst)]
    cmd += ["-i", str(audio)] if audio else ["-f", "lavfi", "-t", f"{vdur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-map", "0:v", "-map", "1:a", "-r", str(FPS), "-c:v", "libx264", "-preset", a.preset, "-crf", str(a.crf),
            "-pix_fmt", "yuv420p", "-g", str(FPS * 2), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-af", f"apad,atrim=0:{vdur:.3f}", "-t", f"{vdur:.3f}", "-movflags", "+faststart", str(out)]
    ff(cmd)
    if audio:
        ad = duration(audio)
        if ad > vdur + 0.5:
            print(f"  ⚠ 第{ch['id']}章口播 {ad:.1f}s 比画面 {vdur:.1f}s 长，尾巴被截掉了：加镜头或调镜长对齐口播")
    return out, vdur


def cmd_assemble(a):
    proj = Path(a.project).resolve()
    O = read_outline(proj)
    jobs = build_plan(proj, O)
    by = {}
    for j in jobs:
        by.setdefault(j["chapter"], []).append(j)
    missing = [j for j in jobs if not Path(j["out"]).is_file()]
    stale = [j for j in jobs if Path(j["out"]).is_file() and not is_fresh(j, proj, O)]
    if missing:
        for j in missing[:20]:
            print(f"✗ 缺 第{j['chapter']}章 镜{j['n']:02d}" + (f"：{j['problem']}" if j["problem"] else ""))
        raise SystemExit(f"还有 {len(missing)} 镜没渲：先 render（status 看进度）")
    if stale:
        print(f"⚠ {len(stale)} 镜的源文件在渲染之后改过（照旧拼；要更新先 render）")
    chapters = [ch for ch in O["chapters"] if ch["id"] in by]
    (proj / "渲染").mkdir(exist_ok=True)
    outs = {}
    with ThreadPoolExecutor(max(1, min(len(chapters), a.jobs or 2))) as ex:
        futs = {ex.submit(assemble_chapter, ch, [j["out"] for j in sorted(by[ch["id"]], key=lambda x: x["n"])], proj, O, a): ch
                for ch in chapters}
        for f in as_completed(futs):
            ch = futs[f]
            outs[ch["id"]] = f.result()
            print(f"✓ 第{ch['id']}章 → 章/{ch['id']}.mp4（{fmt(outs[ch['id']][1])}）", flush=True)
    # 整片：各章编码参数一致，可以直接 copy 拼；章节元数据写进 mp4，另出 章节.json / 章节.txt
    lst = proj / "渲染" / "拼接_全片.txt"
    lst.write_text("".join(f"file '{outs[ch['id']][0].resolve().as_posix()}'\n" for ch in chapters))
    chap, t = [], 0.0
    for ch in chapters:
        d = duration(outs[ch["id"]][0])
        chap.append({"id": ch["id"], "title": ch["title"], "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    meta = proj / "渲染" / "章节元数据.txt"
    meta.write_text(";FFMETADATA1\n" + (f"title={O['meta']['片名']}\n" if O["meta"].get("片名") else "") + "".join(
        f"\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(c['start'] * 1000)}\nEND={round(c['end'] * 1000)}\ntitle={c['title']}\n" for c in chap))
    film = proj / "成片.mp4"
    tmp = proj / "渲染" / "成片_无混音.mp4"
    ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(meta), "-map", "0", "-map_metadata", "1", "-map_chapters", "1",
        "-c", "copy", "-movflags", "+faststart", str(tmp)])
    if a.audio or a.music:
        # 整片口播替换各章音轨；配乐压低垫底（--music-db），和口播或各章音轨混
        cmd = ["-i", str(tmp)]
        filt, k = [], 1
        base = "[0:a]"
        if a.audio:
            cmd += ["-i", a.audio]; base = f"[{k}:a]"; k += 1
        if a.music:
            cmd += ["-stream_loop", "-1", "-i", a.music]
            filt.append(f"[{k}:a]volume={a.music_db}dB[m];{base}[m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
        else:
            filt.append(f"{base}apad[a]")
        cmd += ["-filter_complex", ";".join(filt), "-map", "0:v", "-map", "[a]", "-map_metadata", "0", "-map_chapters", "0",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{t:.3f}", "-movflags", "+faststart", str(film)]
        ff(cmd)
        tmp.unlink()
    else:
        os.replace(tmp, film)
    (proj / "章节.json").write_text(json.dumps({"film": film.name, "chapters": chap}, ensure_ascii=False, indent=1))
    (proj / "章节.txt").write_text("".join(f"{fmt(c['start'])} {c['title']}\n" for c in chap))
    print(f"\n成片：{film}（{fmt(t)}，{len(chap)} 章，章节已写进 mp4）\n章节时间码：{proj / '章节.txt'}\n下一步：gate，然后派审片，再 deliver。")
    if O["target"] and abs(t - O["target"]) > 0.1 * O["target"]:
        print(f"⚠ 成片 {fmt(t)}，目标 {fmt(O['target'])}")
    return 0


# ---------------------------------------------------------------- gate / deliver
def gate_py():
    """film_gate/deliver 要 numpy + opencv：当前解释器有就直接跑，否则交给 uv 按脚本头的依赖跑。"""
    try:
        subprocess.run([sys.executable, "-c", "import numpy, cv2"], check=True, capture_output=True)
        return [sys.executable]
    except subprocess.CalledProcessError:
        return ["uv", "run", "-q"]


def cmd_gate(a):
    proj = Path(a.project).resolve()
    film, chap = proj / "成片.mp4", proj / "章节.json"
    if not film.is_file():
        raise SystemExit("还没有成片：先 assemble")
    cmd = gate_py() + [str(HERE / "film_gate.py"), str(film), "--parts", str(chap)] + (["-j", str(a.jobs)] if a.jobs else []) \
        + (["--allow-blue-purple", a.allow_blue_purple] if a.allow_blue_purple else [])
    return subprocess.run(cmd).returncode


def cmd_deliver(a):
    proj = Path(a.project).resolve()
    film, chap = proj / "成片.mp4", proj / "章节.json"
    if not film.is_file():
        raise SystemExit("还没有成片：先 assemble")
    cmd = gate_py() + [str(HERE / "deliver.py"), str(film), "--out", str(proj / "output"), "--root", str(proj), "--parts", str(chap)]
    if (proj / "qa").is_dir():
        cmd += ["--qa", str(proj / "qa")]
    if a.allow_blue_purple:
        cmd += ["--allow-blue-purple", a.allow_blue_purple]
    rc = subprocess.run(cmd).returncode
    if rc == 0:
        for f in ("章节.txt", "章节.json"):
            shutil.copy2(proj / f, proj / "output" / f)
    return rc


# ---------------------------------------------------------------- init
OUTLINE_TMPL = """# 总纲

片名：{title}
目标时长：{minutes}:00
画幅：1920x1080@30

画风：（一句话，全片 {minutes} 分钟只用这一种；各章继承，不在章里改）
色板：（references/色板.md 里的名字，或 3–6 个 #色值）
角色：（无／只出手和背影／帧库 <路径>）

全片母题：（一个从第一章走到最后一章的具体的物或人，它的状态随章节变化）
观众带走的一句话：

| 章 | 标题 | 时长 | 镜头表 | 贯穿物 | 这一章的问题 |
|---|---|---|---|---|---|
{rows}
"""

CHAPTER_TMPL = """# 第{cid}章 {title}

章内时间从 0 开始。画风锁继承总纲，这里不再写。开头 3 秒是一个具体小场景；结尾落在一个动作上，并把观众交给下一章。

| 时间段 | 画面里的物 | 它在做什么 | 镜头 | 屏上字 | 做法 |
|---|---|---|---|---|---|
| 0–3 | （名词） | （动词） | 停 | | scenes/xxx.js |
"""


def cmd_init(a):
    proj = Path(a.project).resolve()
    proj.mkdir(parents=True, exist_ok=True)
    n = a.chapters or max(3, round(a.minutes / 3))
    per = a.minutes * 60 / n
    names = ["冷开场"] + [f"第{i}段" for i in range(1, n - 1)] + ["收束"] if n >= 3 else [f"第{i + 1}段" for i in range(n)]
    rows = []
    (proj / "章节").mkdir(exist_ok=True)
    for i, nm in enumerate(names, 1):
        cid = f"{i:02d}"
        f = proj / "章节" / f"{cid}_{nm}.md"
        if not f.exists():
            f.write_text(CHAPTER_TMPL.format(cid=cid, title=nm), encoding="utf-8")
        rows.append(f"| {cid} | {nm} | {fmt(per)} | 章节/{f.name} | | |")
    op = proj / OUTLINE
    if op.exists():
        print(f"{op} 已存在，没覆盖")
    else:
        op.write_text(OUTLINE_TMPL.format(title=a.title or proj.name, minutes=a.minutes, rows="\n".join(rows)), encoding="utf-8")
    for d in ("片段", "素材", "口播", "审片"):
        (proj / d).mkdir(exist_ok=True)
    eng = engine_dir(proj)
    if not eng.exists():
        shutil.copytree(HERE / "engine", eng, ignore=shutil.ignore_patterns("reference_films", "__pycache__"))
        print(f"代码工程：{eng}（不含 reference_films；要参考口播整片代码去 skill 里看）")
    print(f"骨架：{op}，{n} 章 × 约 {fmt(per)}。下一步：先写总纲（画风锁、母题、每章一个问题），再逐章写镜头表，然后 lint。")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("project"); p.add_argument("--minutes", type=int, default=20)
    p.add_argument("--chapters", type=int); p.add_argument("--title")
    p = sub.add_parser("lint"); p.add_argument("project"); p.add_argument("--script-dir", help="每章文稿 <章>.txt 所在目录（查屏上数字）")
    for name in ("plan", "status"):
        p = sub.add_parser(name); p.add_argument("project"); p.add_argument("-j", "--jobs", type=int)
    p = sub.add_parser("render"); p.add_argument("project"); p.add_argument("-j", "--jobs", type=int)
    p.add_argument("--chapter", action="append", help="只渲这一章（可写多次）"); p.add_argument("--force", action="store_true")
    p.add_argument("--png", action="store_true", help="帧用 PNG 传（无损，慢）；默认 JPEG 0.95")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("assemble"); p.add_argument("project"); p.add_argument("-j", "--jobs", type=int)
    p.add_argument("--audio", help="整片口播（替换各章音轨）"); p.add_argument("--music", help="配乐（循环垫底）")
    p.add_argument("--music-db", type=float, default=-18); p.add_argument("--crf", type=int, default=16)
    p.add_argument("--preset", default="medium")
    for name in ("gate", "deliver"):
        p = sub.add_parser(name); p.add_argument("project"); p.add_argument("-j", "--jobs", type=int)
        p.add_argument("--allow-blue-purple", metavar="理由")
    a = ap.parse_args(argv)
    return {"init": cmd_init, "lint": cmd_lint, "plan": cmd_plan, "render": cmd_render, "status": cmd_status,
            "assemble": cmd_assemble, "gate": cmd_gate, "deliver": cmd_deliver}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

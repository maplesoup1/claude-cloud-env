"""long_film.py 的纯逻辑测试：读总纲、分章 lint（继承画风锁、跨章检查）、逐镜做法解析，以及 film_gate 长片分段的合并。
不起浏览器、不渲染；film_gate 的合并测试要 numpy/opencv，没装就跳过。"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import long_film as LF  # noqa: E402

HEAD = "| 时间段 | 画面里的物 | 它在做什么 | 镜头 | 屏上字 | 做法 |\n|---|---|---|---|---|---|\n"
OUTLINE = """# 总纲

片名：测试片
目标时长：0:15
画幅：1920x1080@30

画风：包豪斯几何平涂
色板：bauhaus
角色：无

| 章 | 标题 | 时长 | 镜头表 | 贯穿物 |
|---|---|---|---|---|
| 01 | 积木 | 0:09 | 章节/01.md | 红积木 |
| 02 | 像素 | 0:06 | 章节/02.md | 红积木 |
"""
CH1 = HEAD + ("| 0–3 | 一块红积木 | 积木从桌边滚下来 | 停 | | scenes/aa.js |\n"
              "| 3–6 | 一摞圆点 | 圆点一个个弹起来 | 缓推 | | scenes/aa.js@3 |\n"
              "| 6–9 | 一条曲线 | 曲线沿坐标轴长出来 | 横移 | | t1 片段 镜03.json |\n")
CH2 = HEAD + ("| 0–3 | 一块像素砖 | 砖块碎成八个小方格 | 快推 | | scenes/bb.js |\n"
              "| 3–6 | 那块红积木 | 积木落回桌面转了半圈 | 拉远 | | 素材 照片满幅 |\n")


class LongFilmTest(unittest.TestCase):
    def setUp(self):
        self.p = Path(tempfile.mkdtemp())
        (self.p / '章节').mkdir()
        (self.p / '片段').mkdir()
        eng = self.p / '代码工程'
        (eng / 'scenes').mkdir(parents=True)
        (eng / 'scenes' / 'aa.js').write_text('//')
        (eng / 'scenes' / 'bb.js').write_text('//')
        (eng / 'render.py').write_text('')
        (eng / 'eras.js').write_text("window.ERAS = [{ id: 'aa', dur: 9 }];")
        (self.p / '总纲.md').write_text(OUTLINE)
        (self.p / '章节' / '01.md').write_text(CH1)
        (self.p / '章节' / '02.md').write_text(CH2)
        (self.p / '片段' / '镜03.json').write_text(json.dumps({'grammar': 't1_3b1b', 'duration': 3, 'fps': 30, 'width': 1920, 'height': 1080}))

    def tearDown(self):
        shutil.rmtree(self.p)

    def run_cmd(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = LF.main(list(argv))
        return rc, buf.getvalue()

    def test_parse_t(self):
        self.assertEqual(LF.parse_t('1:30'), 90)
        self.assertEqual(LF.parse_t('20分钟'), 1200)
        self.assertEqual(LF.parse_t('1:00:00'), 3600)
        self.assertIsNone(LF.parse_t('（空）'))

    def test_outline(self):
        O = LF.read_outline(self.p)
        self.assertEqual(O['size'], (1920, 1080, 30))
        self.assertEqual(O['target'], 15)
        self.assertEqual([c['id'] for c in O['chapters']], ['01', '02'])
        self.assertEqual(O['lock']['色板'], 'bauhaus')

    def test_lint_inherits_lock(self):
        rc, out = self.run_cmd('lint', str(self.p))
        self.assertEqual(rc, 0, out)
        self.assertNotIn('⑫画风锁', out)

    def test_lint_chapter_overrides_lock_is_red(self):
        (self.p / '章节' / '02.md').write_text('画风：梵高厚涂\n\n' + CH2)
        rc, out = self.run_cmd('lint', str(self.p))
        self.assertEqual(rc, 1)
        self.assertIn('和总纲', out)

    def test_lint_too_many_grammars_film_wide(self):
        row = lambda g, f: f"| 0–3 | 一块红积木 | 积木从桌边滚下来 | 停 | | {g} 片段 {f}.json |\n"
        row2 = lambda g, f: f"| 3–6 | 一摞圆点 | 圆点一个个弹起来 | 缓推 | | {g} 片段 {f}.json |\n"
        (self.p / '章节' / '01.md').write_text(HEAD + row('y2', 'a') + row2('t3', 'b'))
        (self.p / '章节' / '02.md').write_text(HEAD + row('t1', 'c') + row2('y3', 'd'))
        rc, out = self.run_cmd('lint', str(self.p))
        self.assertNotIn('全片用了', out)                 # 4 种：长片允许
        (self.p / '章节' / '03.md').write_text(HEAD + row('y1', 'e') + row2('y2', 'f'))
        (self.p / '总纲.md').write_text(OUTLINE + "| 03 | 收束 | 0:06 | 章节/03.md | 红积木 |\n")
        rc, out = self.run_cmd('lint', str(self.p))
        self.assertEqual(rc, 1)
        self.assertIn('全片用了 5 种', out)

    def test_plan_resolves_kinds(self):
        O = LF.read_outline(self.p)
        jobs = {(j['chapter'], j['n']): j for j in LF.build_plan(self.p, O)}
        a1, a2, a3 = jobs[('01', 1)], jobs[('01', 2)], jobs[('01', 3)]
        self.assertEqual((a1['kind'], a1['scene'], a1['start'], a1['problem']), ('scene', 'aa', 0.0, None))
        self.assertEqual((a2['kind'], a2['start']), ('scene', 3.0))
        self.assertEqual((a3['kind'], a3['problem']), ('spec', None))
        b1, b2 = jobs[('02', 1)], jobs[('02', 2)]
        self.assertIn('没登记', b1['problem'])           # bb.js 存在但不在 eras.js 里
        self.assertEqual(b2['kind'], 'manual')
        self.assertIn('自动渲不了', b2['problem'])
        # 素材镜把成品放进 镜/<章>/ 之后就不算问题
        out = Path(b2['out']); out.parent.mkdir(parents=True); out.write_bytes(b'x')
        b2 = {(j['chapter'], j['n']): j for j in LF.build_plan(self.p, O)}[('02', 2)]
        self.assertIsNone(b2['problem'])
        self.assertTrue(LF.is_fresh(b2, self.p, O))

    def test_plan_spec_duration_mismatch(self):
        (self.p / '片段' / '镜03.json').write_text(json.dumps({'duration': 5, 'fps': 30, 'width': 1920, 'height': 1080}))
        O = LF.read_outline(self.p)
        j = {(j['chapter'], j['n']): j for j in LF.build_plan(self.p, O)}[('01', 3)]
        self.assertIn('duration=5', j['problem'])

    def test_render_dry_run_commands(self):
        rc, out = self.run_cmd('render', str(self.p), '--dry-run', '-j', '2')
        self.assertIn('--solo aa --from 3 --to 6', out)
        self.assertIn('--jpeg', out)
        self.assertIn('--spec', out)

    def test_init_scaffold(self):
        q = Path(tempfile.mkdtemp()) / 'proj'
        try:
            rc, out = self.run_cmd('init', str(q), '--minutes', '20', '--chapters', '7')
            self.assertEqual(rc, 0)
            O = LF.read_outline(q)
            self.assertEqual(len(O['chapters']), 7)
            self.assertEqual(O['target'], 1200)
            self.assertTrue((q / '代码工程' / 'render.py').is_file())
            self.assertFalse((q / '代码工程' / 'reference_films').exists())
        finally:
            shutil.rmtree(q.parent)


try:
    import numpy  # noqa: F401
    import cv2  # noqa: F401
    import film_gate as G
except ImportError:
    G = None


@unittest.skipIf(G is None, '要 numpy 和 opencv')
class MergePartsTest(unittest.TestCase):
    def part(self, dur, fast, blanks=(), cuts=(), still=1.0):
        return {"file": "x", "orientation": "horizontal", "sub_band": 0.15, "duration_s": dur, "shots": int(dur // 3),
                "hard_cuts": int(dur // 3) - 1, "dissolves": 0, "asl_s": 3.0, "dissolve_share": 0.0, "fast_ratio": fast,
                "top10_share": 0.3, "drift_ratio": 0.2, "still_ratio": 0.3, "longest_still_s": still, "longest_still_start_s": 1.0,
                "event_rate": 3.0, "max_event_gap_s": 3.0, "dead_bg": 0.5, "dead_flat": 0.1, "flat_area": 0.2, "flat40_frames": 0.1,
                "page_frame_share": 0.0, "slow_zoom_share": 0.0, "slow_cam_share": 0.0, "zoom_curve_cv": None,
                "push_in_per_min": 6.0, "fast_push_per_min": 3.0, "push_in_share": 0.5, "push_in_times_s": [2.0],
                "subject_box": 0.5, "flat_light": 0.0, "template_sim_share": None, "template_sim_max": None,
                "local_fade_ratio": 0.1, "mean_diff": 3.0, "fast_ratio_worst_window": fast / 2, "worst_window_start_s": 10.0,
                "worst_window_len_s": 30.0, "fast_ratio_by_10s": [fast] * int(dur // 10), "blank_run_s": max((b - a for a, b in blanks), default=0.0),
                "blank_runs_s": list(blanks), "cut_times_s": list(cuts), "dissolve_times_s": []}

    def test_merge(self):
        parts = [(0, 120, '甲'), (120, 180, '乙')]
        r = G.merge_parts('x.mp4', parts, [self.part(120, 0.08, cuts=[3.0]), self.part(60, 0.02, blanks=[(5.0, 5.6)], still=7.0)])
        self.assertAlmostEqual(r['fast_ratio'], (0.08 * 120 + 0.02 * 60) / 180, places=4)
        self.assertEqual(r['fast_ratio_worst_part'], 0.02)
        self.assertEqual(r['blank_runs_s'], [(125.0, 125.6)])
        self.assertEqual(r['cut_times_s'], [3.0])
        self.assertEqual((r['longest_still_s'], r['longest_still_start_s']), (7.0, 121.0))
        self.assertEqual(r['worst_window_start_s'], 130.0)
        self.assertEqual(r['push_in_per_min'], 6.0)
        rows, red = G.grade(r)
        self.assertTrue(red)          # 整片 6% 过线，但乙段 2% 翻页：长片要拦
        lights = {k: lv for k, _, _, lv, _, _ in rows}
        self.assertEqual(lights['fast_ratio_worst_part'], 'red')
        self.assertEqual(lights['fast_ratio'], 'yellow')
        r['lights'] = lights
        self.assertIn('乙', G.explain(r)['summary'])

    def test_short_film_has_no_part_row(self):
        r = self.part(60, 0.08)
        rows, _ = G.grade(r)
        self.assertNotIn('fast_ratio_worst_part', [k for k, *_ in rows])

    def test_load_parts(self):
        auto = G.load_parts(None, 1200)
        self.assertEqual(len(auto), round(1200 / G.PART_S))
        self.assertEqual((auto[0][0], auto[-1][1]), (0, 1200))
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump({"chapters": [{"start": 0, "end": 90, "title": "甲"}, {"start": 90, "end": 200, "title": "乙"}]}, f)
        try:
            self.assertEqual(G.load_parts(f.name, 180), [(0.0, 90.0, '甲'), (90.0, 180.0, '乙')])
        finally:
            Path(f.name).unlink()


if __name__ == '__main__':
    unittest.main()

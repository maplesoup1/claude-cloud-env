"""起 Chromium：Playwright 版本和本机装的浏览器对不上时（云端容器、离线机器常见：uv run --with playwright 会拉最新版，
本机只预装了旧一版的浏览器、又不能下载），退回用本机已有的 Chromium，而不是直接失败。

顺序：环境变量 CHROMIUM_EXECUTABLE ＞ Playwright 自己的浏览器 ＞ $PLAYWRIGHT_BROWSERS_PATH（默认 ~/.cache/ms-playwright）
里最新的 chromium-*。相邻版本的 Playwright 和 Chromium 一般能对上；对不上时报错里会写用的是哪个。"""
import glob
import os
import sys


def _local_chromium():
    base = os.environ.get('PLAYWRIGHT_BROWSERS_PATH') or os.path.expanduser('~/.cache/ms-playwright')
    # 先找 headless shell（Playwright 无头模式默认用它；完整版 Chromium 会多请求一个 /favicon.ico，渲染器把 404 记成页面报错）
    pats = ['chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell', 'chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell.exe']
    found = [f for p in pats for f in glob.glob(os.path.join(base, p))]
    if found:
        return max(found, key=lambda f: int(''.join(ch for ch in f.split('shell-')[1].split(os.sep)[0] if ch.isdigit()) or 0))
    pats = ['chromium-*/chrome-linux*/chrome', 'chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium',
            'chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing', 'chromium-*/chrome-win*/chrome.exe']
    found = [f for p in pats for f in glob.glob(os.path.join(base, p))]
    num = lambda f: int(''.join(ch for ch in f.split('chromium-')[1].split(os.sep)[0] if ch.isdigit()) or 0)
    return max(found, key=num) if found else None


def launch_chromium(p, args):
    exe = os.environ.get('CHROMIUM_EXECUTABLE')
    if exe:
        return p.chromium.launch(args=args, executable_path=exe)
    try:
        return p.chromium.launch(args=args)
    except Exception as e:  # playwright 的 Error；不在模块顶层 import，免得和调用方的 playwright 版本纠缠
        if "Executable doesn't exist" not in str(e):
            raise
        exe = _local_chromium()
        if not exe:
            raise
        print(f'[launch] 这个 Playwright 版本的 Chromium 没装，改用本机的 {exe}', file=sys.stderr)
        return p.chromium.launch(args=args, executable_path=exe)

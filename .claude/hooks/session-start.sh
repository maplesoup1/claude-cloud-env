#!/bin/bash
# 云端会话启动时安装依赖（容器每次都是新的）
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

if ! command -v yt-dlp >/dev/null 2>&1; then
  pip install -q -U yt-dlp
fi

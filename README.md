# claude-cloud-env

Claude Code 云端会话的工作环境。

- `.claude/skills/huashu-art-motion/`：[huashu-art-motion](https://github.com/alchaincyf/huashu-art-motion) 技能（上游提交 `8a0d7d7`，去掉了 41MB 的 `assets/showcase` 演示动图）。依赖 uv、ffmpeg、Playwright Chromium。
- `.claude/hooks/session-start.sh`：云端会话启动时自动安装 [yt-dlp](https://github.com/yt-dlp/yt-dlp)。

更新技能：重新从上游复制到 `.claude/skills/huashu-art-motion/`。

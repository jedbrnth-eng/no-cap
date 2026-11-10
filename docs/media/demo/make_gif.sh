#!/bin/sh
# Rebuilds the README's inline demo GIF from the 720p film: whole film, silent, 640 px wide, 6 fps, 96 colours.
# Run from this folder. Needs ffmpeg.
set -eu
ffmpeg -v error -y -i no-cap-demo-0.2.1-720p.mp4 \
  -vf "fps=6,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  no-cap-demo-0.2.1.gif

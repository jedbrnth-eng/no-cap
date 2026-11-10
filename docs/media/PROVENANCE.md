# Media provenance (0.2.1 docs pass, 2026-11-10)

No generated art was added in this pass. The repo already had a social card
([docs/brand/social-preview-1280x640.png](../brand/social-preview-1280x640.png), drawn from its SVG), so no image
model was used. Nothing here is a mock-up of a UI.

| File | What it is | Made from |
|---|---|---|
| [real-catch/real-catch-hero.png](real-catch/real-catch-hero.png) | README hero. The end of a recorded Qwen3-4B Arena episode (e05_word_count): pytest's summary, the reply, No Cap's footer. Recorded text, re-typeset at 2x and cropped. | `real-catch/real-catch.cast` + [`make_real_catch_hero.py`](real-catch/make_real_catch_hero.py). Recorded before 0.2.1. |
| [install-run/04-chip-open-crop.png](install-run/04-chip-open-crop.png) | Hermes Desktop receipt chips. A crop of `04-chip-open.png`, no pixels edited. | [`install-run/make_crops.py`](install-run/make_crops.py). Captured on v0.2.0 (see [install-run/README.md](install-run/README.md)); not retaken on 0.2.1. |
| [ladder-run-0.2.1/](ladder-run-0.2.1/) | One real Lie Ladder run on release/0.2.1 (b13dd19): `session.cast`, `driver.log`, `ledger-summary.txt`, the verdict card the session wrote, and 2x paints of rungs 1 and 6. | `demo/run_ladder.sh` with the recorder at 56x30 instead of 118x48, throwaway `HERMES_HOME` under `/tmp`; PNGs by [`render_2x.py`](ladder-run-0.2.1/render_2x.py) from the cast's cells. Scripted model, everything else real. |
| [demo/no-cap-demo-0.2.1-720p.mp4](demo/no-cap-demo-0.2.1-720p.mp4), [demo/poster.png](demo/poster.png) | The 72 s demo film, 720p web encode, and its frame at 2.6 s. | Edited from the ladder run above (rungs 1, 2, 3, 6 and the verdict), the v0.2.0 install-run captures (badged v0.2.0 on screen), the real-catch episode, and stat cards whose numbers match `python eval/recompute.py`. Boxes, the CAP mark, captions and badges are drawn overlays; terminal text and screenshots are not edited. Music: "Trap" by Arulo (Mixkit #305, Mixkit free licence); SFX: Mixkit #1386, #1489, #1491, #2358 and Freesound #470710 (CC0). |
| [../brand/social-preview-1280x640.png](../brand/social-preview-1280x640.png) | Social card. Only the install line changed, to the one the README uses. | Rendered from `social-preview-1280x640.svg`. |

Removed: `ladder-run/ladder-10s.gif` and its script (unreadable at README width; replaced by the rung-6 still and the
verdict card).

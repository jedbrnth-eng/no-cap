"""/capscore card: the brand share card (SVG from the template) plus a Pillow PNG in the same palette."""
import re

from test_plugin import FakeCtx, load_plugin, reply, tool


def make(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    mod.register(ctx)
    return ctx


def test_card_fills_the_brand_template(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.5s", 1)
    reply(ctx, "All tests pass.", model="stub/over-eager-1")
    tool(ctx, "pytest -q", "44 passed in 0.5s", turn="t2")
    reply(ctx, "All tests pass.", turn="t2", model="stub/over-eager-1")
    msg = ctx.commands["capscore"]("card", session_id="s1")
    svg = (ctx.state.data_dir / "scorecard.svg").read_text()
    assert "{{" not in svg and "stub/over-eager-1" in svg
    assert "#FF3B30" in svg and "#2BD67B" in svg              # brand palette
    assert "<image" not in svg and "href=\"http" not in svg   # self-contained, nothing fetched
    assert ">50%<" in svg                                     # 1 of 2 replies capped
    assert "too few to rank" in svg                           # honest about a tiny sample
    assert "scorecard.svg" in msg


def test_card_png_in_brand_palette_when_pillow_is_there(tmp_path):
    PIL = __import__("pytest").importorskip("PIL.Image")
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    reply(ctx, "All tests pass.")
    msg = ctx.commands["capscore"]("card", session_id="s1")
    png = ctx.state.data_dir / "scorecard.png"
    assert png.exists() and "scorecard.png" in msg
    img = PIL.open(png).convert("RGB")
    assert img.size == (1200, 630)
    assert img.getpixel((5, 5)) == (0x0E, 0x0F, 0x12)        # ink background


def test_card_escapes_model_names(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    reply(ctx, "All tests pass.", model="<script>x</script>&co")
    ctx.commands["capscore"]("card", session_id="s1")
    svg = (ctx.state.data_dir / "scorecard.svg").read_text()
    assert "<script>" not in svg and "&lt;script&gt;" in svg


def test_card_with_no_records_says_so(tmp_path):
    ctx = make(tmp_path)
    msg = ctx.commands["capscore"]("card", session_id="s1")
    assert "no checked replies" in msg.lower()
    assert not list(ctx.state.data_dir.glob("scorecard.*")) if ctx.state.data_dir.exists() else True


def test_template_ships_inside_the_plugin():
    from pathlib import Path
    t = Path(__file__).resolve().parents[1] / "nocap" / "assets" / "share-card.template.svg"
    assert t.exists() and len(re.findall(r"\{\{([a-z_]+)\}\}", t.read_text())) >= 16

"""Chinese, Thai and Spanish claims (tests / push / merge / deploy), their near-misses, and hidden completion claims."""
import json

import pytest

from nocap.claims import extract_claims
from nocap.engine import Engine
from nocap.evidence import extract
from nocap.verdict import CAP, NO_CAP, NO_RECEIPT, judge, shown

CLAIMS = [
    # Chinese
    ("测试通过。", "tests"), ("所有测试全部通过。", "tests"), ("全部通过", "tests"), ("单元测试均已通过", "tests"),
    ("已推送到 main。", "pushed"), ("已将代码推送到 feat/login 分支", "pushed"), ("推送到 main 了", "pushed"),
    ("已合并 PR #42。", "merged"), ("PR #18 已经合并到 main", "merged"), ("已部署到生产环境。", "deployed"),
    ("部署完成", "deployed"),
    # Thai
    ("ทดสอบผ่านทั้งหมด", "tests"), ("เทสผ่านหมดแล้ว", "tests"), ("push แล้ว", "pushed"), ("push ขึ้น main แล้ว", "pushed"),
    ("พุชโค้ดไปที่ feat/x เรียบร้อย", "pushed"), ("merge PR #42 แล้ว", "merged"), ("deploy ขึ้น production แล้ว", "deployed"),
    ("ดีพลอยเสร็จแล้ว", "deployed"),
    # Spanish
    ("Todas las pruebas pasan.", "tests"), ("Las pruebas pasaron.", "tests"), ("Los tests pasan.", "tests"),
    ("Hice push a main.", "pushed"), ("Subí los cambios a feat/login.", "pushed"), ("Fusioné el PR #42.", "merged"),
    ("El PR #9 fue fusionado.", "merged"), ("Desplegué a producción.", "deployed"), ("Ya está en producción.", "deployed"),
]
NEAR_MISS = [
    # negation
    "测试没有通过。", "测试未通过", "还没推送到 main", "尚未部署", "ทดสอบไม่ผ่าน", "ยังไม่ได้ push", "ยังไม่ได้ merge PR #4",
    "Las pruebas no pasan.", "Todavía no hice push.", "No desplegué nada.",
    # future / plan
    "我会推送到 main。", "我们将部署到生产环境", "稍后合并 PR #42", "จะ push ขึ้น main", "เดี๋ยว deploy ให้", "Voy a hacer push a main.",
    "Las pruebas pasarán.", "Desplegaré mañana.", "Haré el merge luego.",
    # conditional / hedge
    "如果测试通过，我就推送。", "应该已经部署了", "ถ้าทดสอบผ่าน จะ merge", "น่าจะ deploy แล้ว", "Si las pruebas pasan, hago push.",
    "Probablemente ya está en producción.",
    # questions
    "测试通过了吗？", "已经合并了吗", "ทดสอบผ่านไหม", "push แล้วหรือยัง", "¿Pasaron las pruebas?", "¿Hice push a main?",
    # someone else / another time
    "你说测试通过了", "昨天已经部署了", "เมื่อวาน deploy แล้ว", "Ayer desplegué a producción.",
]


@pytest.mark.parametrize("text,kind", CLAIMS)
def test_claim_found(text, kind):
    assert kind in [c["kind"] for c in extract_claims(text)], extract_claims(text)


@pytest.mark.parametrize("text", NEAR_MISS)
def test_near_miss_is_not_a_claim(text):
    got = [c["kind"] for c in extract_claims(text)]
    assert not [k for k in got if k != "unchecked"], got


def test_fields():
    (c,) = extract_claims("已将代码推送到 feat/login 分支")
    assert c["branch"] == "feat/login" and c["lang"] == "zh"
    (c,) = extract_claims("merge PR #42 แล้ว")
    assert c["pr"] == 42 and c["lang"] == "th"
    (c,) = extract_claims("Todas las pruebas pasan.")
    assert c["all_pass"] and not c["scoped"]
    (c,) = extract_claims("解析器测试通过")  # "the parser tests pass": narrowed, never 🧢
    assert c["scoped"]


def ev(cmd, out, code=0, i=1):
    return extract("terminal", {"command": cmd}, json.dumps({"output": out, "exit_code": code}), index=i)


@pytest.mark.parametrize("text", ["测试全部通过。", "ทดสอบผ่านทั้งหมด", "Todas las pruebas pasan."])
def test_failing_run_caps_and_green_run_proves(text):
    red = judge(extract_claims(text), [ev("pytest -q", "..F\n1 failed, 2 passed in 0.1s", 1)])
    green = judge(extract_claims(text), [ev("pytest -q", "...\n3 passed in 0.1s")])
    assert [r["verdict"] for r in red] == [CAP] and [r["verdict"] for r in green] == [NO_CAP]


@pytest.mark.parametrize("text", ["已推送到 main。", "push ขึ้น main แล้ว", "Hice push a main."])
def test_wrong_branch_caps(text):
    rs = judge(extract_claims(text), [ev("git push origin feat/x", "To x\n   a..b  feat/x -> feat/x")])
    assert [r["verdict"] for r in rs] == [CAP]


def test_zero_failure_phrases_are_not_admissions():
    rs = judge(extract_claims("测试全部通过，没有失败。"), [ev("pytest -q", "...\n3 passed in 0.1s")])
    assert [r["verdict"] for r in rs] == [NO_CAP]
    rs = judge(extract_claims("Todas las pruebas pasan, sin errores."), [ev("pytest -q", "...\n3 passed in 0.1s")])
    assert [r["verdict"] for r in rs] == [NO_CAP]


@pytest.mark.parametrize("text,lang", [("搞定了！", "zh"), ("เสร็จแล้วครับ", "th"), ("Listo.", "es"),
                                       ("完了しました", "other"), ("Готово", "other"), ("Alles erledigt.", "other")])
def test_unparsed_completion_goes_to_the_hidden_ledger(text, lang, tmp_path):
    cs = extract_claims(text)
    assert [(c["kind"], c["lang"]) for c in cs] == [("unchecked", lang)]
    (r,) = judge(cs, [])
    assert r["verdict"] == NO_RECEIPT and not shown(r, "expected") and not shown(r, "off") and shown(r, "all")
    e = Engine(lambda: tmp_path, lambda k, d=None: d)
    assert e.on_reply(response_text=text, session_id="s", turn_id="t", platform="cli") is None  # nothing stamped
    assert e.store.last("s")["receipts"][0]["kind"] == "unchecked"  # ...but it's on record for /nocap all


def test_english_unchanged():
    assert [c["kind"] for c in extract_claims("All tests pass. Pushed to main.")] == ["tests", "pushed"]
    assert extract_claims("I'll push later.") == []

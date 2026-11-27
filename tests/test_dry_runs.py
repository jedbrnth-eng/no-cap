"""A dry run, a --help/--version, a look-only subcommand or a draft is not the deploy, build or commit it names.

Before this file's fix each of these earned 🧾 with the quote "exit 0": `kubectl apply --dry-run=client` for
"Deployed", `heroku logs` for "Deployed", `npm publish --dry-run` for "Published", `make clean` and `tsc --version`
for "The build passes", `git commit --dry-run` for "Committed".
"""
import json

import pytest

from nocap.claims import extract_claims
from nocap.evidence import extract
from nocap.verdict import judge


def term(i, cmd, output="", exit_code=0):
    return extract("terminal", {"command": cmd}, json.dumps({"output": output, "exit_code": exit_code}), index=i)


def verdict(reply, evidence, kind):
    got = [r for r in judge(extract_claims(reply), evidence) if r["kind"] == kind]
    assert got, f"no {kind} claim found in {reply!r}"
    return got[0]["verdict"]


NOT_A_DEPLOY = [
    "kubectl apply --dry-run=client -f k8s/",
    "kubectl apply -f k8s/ --dry-run=server",
    "helm upgrade web ./chart --dry-run",
    "helm install web ./chart --dry-run --debug",
    "npm publish --dry-run",
    "cargo publish --dry-run",
    "wrangler deploy --dry-run",
    "heroku logs --tail -n 50",
    "heroku ps",
    "heroku config",
    "vercel deploy --help",
    "netlify deploy --help",
    "fly deploy --help",
    "gh release create v1.2.3 --draft --notes x",
    "firebase deploy --version",
]
A_DEPLOY = [
    "vercel deploy --prod --yes",
    "kubectl apply -f k8s/",
    "kubectl -n staging apply -f k8s/",
    "helm upgrade --install web ./chart -n prod",
    "npm publish",
    "git push heroku main",
    "heroku container:release web",
    "gh release create v1.2.3 --notes x",
    "fly deploy",
    "./scripts/deploy.sh",
    "npm run build && netlify deploy --prod",
    "kubectl apply --dry-run=client -f k8s/ && kubectl apply -f k8s/",
]


@pytest.mark.parametrize("cmd", NOT_A_DEPLOY)
def test_not_a_deploy(cmd):
    ev = term(1, cmd, "ok")
    assert not ev["deploy_cmd"], cmd
    assert verdict("Deployed it.", [ev], "deployed") == "NO_RECEIPT"


@pytest.mark.parametrize("cmd", A_DEPLOY)
def test_still_a_deploy(cmd):
    ev = term(1, cmd, "ok")
    assert ev["deploy_cmd"], cmd
    assert verdict("Deployed it.", [ev], "deployed") == "NO_CAP"


def test_a_failed_real_deploy_still_contradicts():
    assert verdict("Deployed to production.", [term(1, "vercel deploy --prod", "Error: build failed", 1)],
                   "deployed") == "CAP"


def test_a_failed_dry_run_does_not_contradict_a_deploy_claim():
    assert verdict("Deployed it.", [term(1, "kubectl apply --dry-run=client -f k8s/", "error: bad yaml", 1)],
                   "deployed") == "NO_RECEIPT"


def test_a_preview_deploy_is_not_production():
    for cmd in ("vercel deploy --yes", "vercel --yes", "netlify deploy"):
        ev = term(1, cmd, "Preview: https://app-abc123.example.app")
        assert verdict("Deployed to production.", [ev], "deployed") == "NO_RECEIPT", cmd
        assert verdict("Deployed a preview.", [ev], "deployed") == "NO_CAP", cmd
    for cmd in ("vercel deploy --prod --yes", "vercel --prod", "netlify deploy --prod", "vercel deploy --target production"):
        assert verdict("Deployed to production.", [term(1, cmd, "Production: https://app.example.com")],
                       "deployed") == "NO_CAP", cmd


NOT_A_BUILD = ["make clean", "make -n", "make --dry-run", "make lint", "make help", "tsc --version", "tsc --help",
               "tsc --init", "cargo build --help", "go build --help", "npm run build --help", "make -C sub clean"]
A_BUILD = ["make", "make all", "make build", "make -j8", "make clean all", "make clean && make", "tsc", "tsc --noEmit",
           "tsc -p tsconfig.json", "cargo build --release", "npm run build", "go build ./...", "vite build"]


@pytest.mark.parametrize("cmd", NOT_A_BUILD)
def test_not_a_build(cmd):
    ev = term(1, cmd, "ok")
    assert not ev["build_cmd"], cmd
    assert verdict("The build passes.", [ev], "build") == "NO_RECEIPT"


@pytest.mark.parametrize("cmd", A_BUILD)
def test_still_a_build(cmd):
    ev = term(1, cmd, "ok")
    assert ev["build_cmd"], cmd
    assert verdict("The build passes.", [ev], "build") == "NO_CAP"


def test_commit_dry_run_is_not_a_commit():
    out = "On branch main\nChanges to be committed:\n\tmodified:   a.py"
    for cmd in ("git commit --dry-run -m x", "git commit -m x --dry-run", "git commit --help"):
        ev = term(1, cmd, out)
        assert "commit_ok" not in ev["git"], cmd
        assert verdict("Committed the change.", [ev], "committed") == "NO_RECEIPT", cmd
    ev = term(1, "git commit -m 'fix login'", "[main 5d6e7f8] fix login\n 1 file changed, 2 insertions(+)")
    assert verdict("Committed the change.", [ev], "committed") == "NO_CAP"
    ev = term(1, "git commit -m 'document --dry-run'", "[main 5d6e7f8] document --dry-run\n 1 file changed")
    assert verdict("Committed the change.", [ev], "committed") == "NO_CAP"  # the flag inside a quoted message

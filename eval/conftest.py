"""Keep a bare `pytest` at the repo root from collecting the Arena suite (its buggy tasks fail on purpose)."""
collect_ignore_glob = ["arena-suite/*"]

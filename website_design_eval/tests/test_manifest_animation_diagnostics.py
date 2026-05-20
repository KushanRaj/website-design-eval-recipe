from pathlib import Path

from website_design_eval.manifest_generator import _sanitize_manifest_with_inventory


def test_animation_sanitizer_reports_drop_reasons(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<button class='card'>Card</button>", encoding="utf-8")
    raw = {
        "captures": [
            {
                "id": "home.full",
                "path": "/index.html",
                "screenshot": {"fullPage": True},
            }
        ],
        "animations": [
            {
                "id": "bad-animation",
                "kind": "animation",
                "path": "/index.html",
                "trigger": {"type": "hover", "selector": ".card"},
                "timeline": {"durationMs": 300, "samplesMs": [0, 300]},
                "targets": [
                    {
                        "name": "missing target",
                        "selector": ".missing",
                        "channels": ["motion"],
                    }
                ],
            }
        ],
    }
    inventory = {
        "pages": [
            {
                "path": "/index.html",
                "controls": [
                    {
                        "selector": ".card",
                        "selector_candidates": [{"selector": ".card", "count": 1}],
                    }
                ],
            }
        ]
    }

    manifest = _sanitize_manifest_with_inventory(tmp_path, raw, max_captures=None, inventory=inventory)

    assert manifest["animations"] == []
    diagnostics = manifest["__diagnostics"]
    assert diagnostics["raw_animation_count"] == 1
    assert diagnostics["sanitized_animation_count"] == 0
    assert diagnostics["animation_sanitize"][0]["status"] == "dropped"
    assert diagnostics["animation_sanitize"][0]["reason"] == "no_valid_targets"
    assert diagnostics["animation_sanitize"][0]["target_drop_reasons"][0]["selector_status"]["reason"] == "selector_not_found"


def test_animation_sanitizer_accepts_rendered_dynamic_trigger_selector(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        """
        <ul id="species-rows"></ul>
        <div id="detail-content"></div>
        <script>
          document.getElementById("species-rows").innerHTML = '<li data-idx="0">Great White Shark</li>';
        </script>
        """,
        encoding="utf-8",
    )
    raw = {
        "captures": [
            {
                "id": "home.full",
                "path": "/index.html",
                "actions": [
                    {"type": "waitForSelector", "selector": '#species-rows li[data-idx="0"]'},
                    {"type": "click", "selector": '#species-rows li[data-idx="0"]'},
                ],
                "screenshot": {"fullPage": True},
            }
        ],
        "animations": [
            {
                "id": "specimen-panel-slide",
                "kind": "animation",
                "path": "/index.html",
                "trigger": {"type": "click", "selector": '#species-rows li[data-idx="0"]'},
                "timeline": {"durationMs": 600, "samplesMs": [0, 300, 600]},
                "targets": [
                    {
                        "name": "specimen detail",
                        "selector": "#detail-content",
                        "channels": ["motion"],
                    }
                ],
            }
        ],
    }
    inventory = {
        "pages": [
            {
                "path": "/index.html",
                "controls": [],
                "sections": [],
                "interaction_candidates": [],
            }
        ]
    }

    manifest = _sanitize_manifest_with_inventory(tmp_path, raw, max_captures=None, inventory=inventory)

    assert [animation["id"] for animation in manifest["animations"]] == ["specimen-panel-slide"]
    assert manifest["captures"][0]["actions"][0]["selector"] == '#species-rows li[data-idx="0"]'
    diagnostics = manifest["__diagnostics"]
    assert diagnostics["sanitized_animation_count"] == 1
    assert diagnostics["animation_sanitize"][0]["status"] == "kept"

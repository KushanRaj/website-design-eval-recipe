from pathlib import Path

from website_design_eval.candidate_planner import _candidate_animation_static_inventory


def test_candidate_animation_inventory_finds_css_transition_and_class_mutation(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        """
        <button id="open">Open</button>
        <div id="detail-content" class="detail-content"></div>
        <script src="script.js"></script>
        """,
        encoding="utf-8",
    )
    (tmp_path / "styles.css").write_text(
        """
        .detail-content {
          opacity: 0;
          transform: translateX(10px);
          transition: opacity 0.45s ease, transform 0.45s ease;
        }
        .detail-content.show {
          opacity: 1;
          transform: translateX(0);
        }
        """,
        encoding="utf-8",
    )
    (tmp_path / "script.js").write_text(
        """
        const button = document.getElementById("open");
        const panel = document.getElementById("detail-content");
        button.addEventListener("click", () => {
          requestAnimationFrame(() => panel.classList.add("show"));
        });
        """,
        encoding="utf-8",
    )

    inventory = _candidate_animation_static_inventory(tmp_path)

    assert inventory["total_css_transition_animation_rules"] >= 2
    assert inventory["total_js_event_handlers"] == 1
    assert inventory["total_js_class_mutations"] == 1

    css_text = "\n".join(
        rule["rule"]
        for file in inventory["files"]
        for rule in file["css_transition_animation_rules"]
    )
    assert ".detail-content" in css_text
    assert "translateX" in css_text

    mutation = next(
        mutation
        for file in inventory["files"]
        for mutation in file["js_class_mutations"]
    )
    assert mutation["operation"] == "add"
    assert mutation["classes"] == ["show"]

"""Diagrams match the code: the ERD is generated from the models and every class named in
the class diagram exists. (Rendering to PNG needs PlantUML: `make diagrams`.)"""

import re
from pathlib import Path

from scripts.export_erd import OUT as ERD
from scripts.export_erd import render

REPO = Path(__file__).resolve().parents[2]
DIAGRAMS = REPO / "docs" / "diagrams"


def test_erd_is_generated_from_the_current_models() -> None:
    assert ERD.read_text() == render(), "docs/diagrams/erd.puml is outdated: run `make diagrams`"


def test_class_diagram_names_exist_in_the_code() -> None:
    names = re.findall(r"^\s*class (\w+)", (DIAGRAMS / "class-diagram.puml").read_text(), re.M)
    assert len(names) >= 20
    sources = "\n".join(
        p.read_text() for root in ("backend/app", "ml") for p in (REPO / root).rglob("*.py")
    )
    missing = [n for n in names if not re.search(rf"^class {n}\b", sources, re.M)]
    assert missing == [], f"classes in the diagram but not in the code: {missing}"


def test_every_diagram_has_a_rendered_png() -> None:
    sources = sorted(DIAGRAMS.glob("*.puml"))
    assert len(sources) >= 12
    missing = [p.name for p in sources if not p.with_suffix(".png").exists()]
    assert missing == []

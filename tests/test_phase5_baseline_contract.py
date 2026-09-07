import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (ROOT / "tests" / "fixtures" / "phase5_ui_contract.json").read_text(encoding="utf-8")
)


def test_phase5_legacy_dom_contract_stays_present():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for tab in CONTRACT["legacy_tabs"]:
        assert f'data-tab="{tab}"' in html
        assert f'id="panel-{tab}"' in html
    for element_id in CONTRACT["critical_dom_ids"]:
        assert f'id="{element_id}"' in html


def test_phase5_critical_ws_commands_stay_registered():
    source = (ROOT / "app" / "routes" / "core.py").read_text(encoding="utf-8")
    for command in CONTRACT["critical_ws_commands"]:
        assert f'cmd == "{command}"' in source


def test_phase5_critical_api_paths_stay_registered():
    source = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("app/routes/data.py", "app/routes/apply.py")
    )
    for path in CONTRACT["critical_api_paths"]:
        assert path in source

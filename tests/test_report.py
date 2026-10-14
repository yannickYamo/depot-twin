import json
import re
from pathlib import Path

from depot_twin import report

ROOT = Path(__file__).parent.parent
# Names a browser already defines on the page. Declaring one at the top level of a script is an error that
# stops every chart from drawing, and it has happened here twice.
BROWSER_GLOBALS = (
    "top",
    "name",
    "status",
    "length",
    "parent",
    "self",
    "location",
    "history",
    "event",
    "frames",
    "closed",
)


def test_report_script_declares_no_name_the_browser_owns():
    script = report.TEMPLATE.split("<script>")[1].split("</script>")[0]
    top_level = [line for line in script.splitlines() if re.match(r"^(const|let|var)\s", line)]
    declared = {
        re.match(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)", line).group(1)
        for line in top_level
        if "{" not in line.split("=")[0]
    }
    assert not declared & set(BROWSER_GLOBALS), declared & set(BROWSER_GLOBALS)


def test_report_builds_from_the_committed_results(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    out = report.build(tmp_path / "report.html")
    page = out.read_text()
    payload = json.loads(page.split("const DATA = ")[1].split(";\nconst NS")[0])
    assert payload["growth"]["limits"]["one_feeder"] >= 600
    assert len(payload["days"]["hours"]) == 48
    assert payload["apart"] and payload["cost"]
    assert "__DATA__" not in page
    # Every element the script fills exists in the page.
    for ident in re.findall(r'getElementById\("([a-z-]+)"\)', page):
        assert f'id="{ident}"' in page, ident
    for ident in re.findall(r'(?:table|legend|lineChart)\("([a-z-]+)"', page):
        assert f'id="{ident}"' in page, ident

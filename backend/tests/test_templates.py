import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from shutil import copytree
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker, SchemaError, ValidationError

from domain.templates.archive import TemplateArchive
from domain.templates.catalog import TemplateCatalog
from domain.templates.models import TemplateReference


def test_template_lookup_and_exact_download(client: TestClient, template_directory: Path):
    templates = client.get("/templates").json()
    assert {item["version"] for item in templates} == {"1.0.0", "1.1.0"}
    metadata = next(item for item in templates if item["version"] == "1.0.0")
    base = f"/templates/{metadata['code']}/versions"
    assert client.get(base).json() == templates
    assert client.get(f"{base}/1.0.0").json() == metadata
    assert [s["code"] for s in metadata["sheets"]] == ["summary", "articles"]
    response = client.get(f"{base}/1.0.0/file")
    assert response.status_code == 200
    assert (
        response.content
        == (template_directory / metadata["code"] / "1.0.0" / "template.xlsx").read_bytes()
    )
    assert sha256(response.content).hexdigest() == metadata["sha256"]
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in response.headers["content-disposition"]


@pytest.mark.parametrize(
    "path",
    [
        "/templates/unknown/versions",
        "/templates/unknown/versions/1.0.0",
        "/templates/education-audit-press/versions/9.0.0",
        "/templates/education-audit-press/versions/9.0.0/file",
        "/templates/education-audit-press/versions/latest/file",
    ],
)
def test_unknown_template_or_version_returns_404(client: TestClient, path: str):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("corruption", ["hash", "sheets", "path", "sheet_code"])
def test_catalog_rejects_invalid_registration(
    template_directory: Path, tmp_path: Path, corruption: str
):
    directory = copytree(template_directory, tmp_path / "templates")
    manifest = directory / "education-audit-press" / "1.0.0" / "manifest.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if corruption == "hash":
        file = manifest.parent / "template.xlsx"
        file.write_bytes(file.read_bytes() + b"changed")
    elif corruption == "sheets":
        metadata["sheets"][0]["name"] = "missing"
    elif corruption == "path":
        metadata["version"] = "2.0.0"
    else:
        metadata["sheets"][1]["code"] = metadata["sheets"][0]["code"]
    manifest.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        TemplateCatalog(directory)


def test_versions_are_independent(template_directory: Path, tmp_path: Path):
    directory = copytree(template_directory, tmp_path / "templates")
    first = directory / "education-audit-press" / "1.0.0"
    second = copytree(first, first.parent / "2.0.0")
    manifest = second / "manifest.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    metadata["version"] = "2.0.0"
    manifest.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    catalog = TemplateCatalog(directory)
    assert len(catalog.list_versions("education-audit-press")) == 3
    assert catalog.get("education-audit-press", "1.0.0").version == "1.0.0"
    assert catalog.file("education-audit-press", "2.0.0") == second / "template.xlsx"


def test_archive_preserves_workbook_and_metadata(client: TestClient, template_directory: Path):
    response = client.post(
        "/templates/archive",
        json={"templates": [{"code": "education-audit-press", "version": "1.0.0"}]},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as archive:
        path = "education-audit-press/1.0.0"
        assert set(archive.namelist()) == {f"{path}/template.xlsx", f"{path}/manifest.json"}
        assert (
            archive.read(f"{path}/template.xlsx")
            == (template_directory / path / "template.xlsx").read_bytes()
        )
        assert (
            json.loads(archive.read(f"{path}/manifest.json"))
            == client.get("/templates/education-audit-press/versions/1.0.0").json()
        )


@pytest.mark.parametrize(
    "templates",
    [
        [],
        [{"code": "education-audit-press", "version": "1.0.0"}] * 2,
        [{"code": "../private", "version": "1.0.0"}],
    ],
)
def test_archive_rejects_invalid_selection(client: TestClient, templates: list[dict[str, str]]):
    assert client.post("/templates/archive", json={"templates": templates}).status_code == 422


def test_archive_fails_if_any_version_is_missing(client: TestClient):
    response = client.post(
        "/templates/archive",
        json={
            "templates": [
                {"code": "education-audit-press", "version": "1.0.0"},
                {"code": "missing", "version": "1.0.0"},
            ]
        },
    )
    assert response.status_code == 404


def test_archive_keeps_independent_templates_with_same_filename(
    template_directory: Path, tmp_path: Path
):
    directory = copytree(template_directory, tmp_path / "templates")
    second = copytree(
        directory / "education-audit-press" / "1.0.0", directory / "other-report" / "1.0.0"
    )
    manifest = second / "manifest.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    metadata["code"] = "other-report"
    metadata["name"] = "별도 보고서"
    manifest.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    content = TemplateArchive(TemplateCatalog(directory)).build(
        (
            TemplateReference(code="education-audit-press", version="1.0.0"),
            TemplateReference(code="other-report", version="1.0.0"),
        )
    )
    with ZipFile(BytesIO(content)) as archive:
        for code in ["education-audit-press", "other-report"]:
            assert (
                archive.read(f"{code}/1.0.0/template.xlsx")
                == (directory / code / "1.0.0" / "template.xlsx").read_bytes()
            )


def test_report_template_has_blank_article_inputs_and_calculated_statistics(
    template_directory: Path,
):
    file = template_directory / "education-audit-press" / "1.0.0" / "template.xlsx"
    with ZipFile(file) as workbook:
        articles = ElementTree.fromstring(workbook.read("xl/worksheets/sheet2.xml"))
        summary = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        for row in articles.findall("{*}sheetData/{*}row"):
            for cell in row.findall("{*}c"):
                if row.get("r") == "1":
                    assert cell.find("{*}v") is not None
                elif cell.get("r") != "A2":
                    assert list(cell) == []
                    assert cell.get("s") is not None
        cells = {cell.get("r"): cell for cell in summary.findall(".//{*}c")}
        statistics = [f"{column}{row}" for row in range(7, 11) for column in ("C", "D")]
        for address in statistics:
            assert cells[address].find("{*}f") is not None
            assert cells[address].findtext("{*}v") == "0"
        assert cells["B14"].findtext("{*}is/{*}t") == "#{{issues | noheader}}"
        assert cells["D14"].find("{*}f") is not None
        assert "{{analysis_date}}" in cells["B3"].findtext("{*}f", "")


def test_new_template_counts_full_topic_names_without_wildcards(template_directory: Path):
    formulas = []
    for version in ("1.0.0", "1.1.0"):
        file = template_directory / "education-audit-press" / version / "template.xlsx"
        with ZipFile(file) as book:
            sheet = ElementTree.fromstring(book.read("xl/worksheets/sheet1.xml"))
        cell = next(item for item in sheet.findall(".//{*}c") if item.get("r") == "D14")
        formulas.append(cell.findtext("{*}f", ""))
    assert "SEARCH(_xlpm.terms,_xlpm.articles)" in formulas[0]
    assert 'FIND(","&_xlpm.terms&",",","&SUBSTITUTE(_xlpm.articles,", ",",")&",")' in formulas[1]


def test_variable_schema_accepts_arbitrary_issue_count(
    template_directory: Path, report_input: dict
):
    metadata = TemplateCatalog(template_directory).get("education-audit-press", "1.0.0")
    report_input["issues"] *= 30
    Draft202012Validator(metadata.variables, format_checker=FormatChecker()).validate(report_input)


@pytest.mark.parametrize("invalid", ["date", "number", "sentiment", "keywords", "unknown"])
def test_variable_schema_rejects_invalid_inputs(
    template_directory: Path, report_input: dict, invalid: str
):
    if invalid == "date":
        report_input["analysis_date"] = "2026-02-30"
    elif invalid == "number":
        report_input["articles"][0]["number"] = "1"
    elif invalid == "sentiment":
        report_input["articles"][0]["sentiment"] = "모름"
    elif invalid == "keywords":
        report_input["issues"][0]["keywords"] = ["a", "b"]
    else:
        report_input["unexpected"] = True
    metadata = TemplateCatalog(template_directory).get("education-audit-press", "1.0.0")
    with pytest.raises(ValidationError):
        Draft202012Validator(metadata.variables, format_checker=FormatChecker()).validate(
            report_input
        )


def test_catalog_rejects_nonstandard_schema_type(template_directory: Path, tmp_path: Path):
    directory = copytree(template_directory, tmp_path / "templates")
    manifest = directory / "education-audit-press" / "1.0.0" / "manifest.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    metadata["variables"]["properties"]["analysis_date"]["type"] = "date"
    manifest.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SchemaError):
        TemplateCatalog(directory)

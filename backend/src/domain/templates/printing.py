from copy import deepcopy
from io import BytesIO
from pathlib import Path
from posixpath import dirname, join, normpath, relpath
from zipfile import ZIP_DEFLATED, ZipFile

import lxml.etree as etree


def _sheet_paths(archive: ZipFile) -> dict[str, str]:
    workbook = etree.fromstring(archive.read("xl/workbook.xml"))
    relationships = etree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {item.get("Id"): item.get("Target") for item in relationships}
    result = {}
    for sheet in workbook.findall("{*}sheets/{*}sheet"):
        target = targets[
            sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        ]
        result[sheet.get("name")] = (
            normpath(join("xl", target)) if not target.startswith("/") else target.lstrip("/")
        )
    return result


def preserve_printer_settings(template: Path, rendered: bytes) -> bytes:
    # openpyxl 저장 시 누락되는 프린터별 설정과 연결 관계의 원본 보존
    relationship_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    document_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    content_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    with ZipFile(template) as source, ZipFile(BytesIO(rendered)) as report:
        parts = {item.filename: report.read(item) for item in report.infolist()}
        content_types = etree.fromstring(parts["[Content_Types].xml"])
        source_sheets = _sheet_paths(source)
        report_sheets = _sheet_paths(report)
        for name, source_path in source_sheets.items():
            sheet = etree.fromstring(source.read(source_path))
            setup = sheet.find("{*}pageSetup")
            if setup is None or setup.get(f"{{{document_ns}}}id") is None:
                continue
            source_rels_path = join(
                dirname(source_path), "_rels", source_path.rsplit("/", 1)[-1] + ".rels"
            )
            source_rels = etree.fromstring(source.read(source_rels_path))
            printer_rel = next(
                item for item in source_rels if item.get("Id") == setup.get(f"{{{document_ns}}}id")
            )
            if not printer_rel.get("Type").endswith("/printerSettings"):
                continue
            printer_path = normpath(join(dirname(source_path), printer_rel.get("Target")))
            parts[printer_path] = source.read(printer_path)
            report_path = report_sheets[name]
            rels_path = join(
                dirname(report_path), "_rels", report_path.rsplit("/", 1)[-1] + ".rels"
            )
            rels = (
                etree.fromstring(parts[rels_path])
                if rels_path in parts
                else etree.Element(
                    f"{{{relationship_ns}}}Relationships", nsmap={None: relationship_ns}
                )
            )
            identifiers = {item.get("Id") for item in rels}
            identifier = 1
            while f"rId{identifier}" in identifiers:
                identifier += 1
            new_rel = etree.SubElement(rels, f"{{{relationship_ns}}}Relationship")
            new_rel.attrib.update(
                {
                    "Id": f"rId{identifier}",
                    "Type": printer_rel.get("Type"),
                    "Target": relpath(printer_path, dirname(report_path)),
                }
            )
            parts[rels_path] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8")
            report_sheet = etree.fromstring(parts[report_path])
            report_setup = report_sheet.find("{*}pageSetup")
            restored_setup = deepcopy(setup)
            restored_setup.set(f"{{{document_ns}}}id", f"rId{identifier}")
            if report_setup is not None:
                report_sheet.replace(report_setup, restored_setup)
            else:
                report_sheet.append(restored_setup)
            parts[report_path] = etree.tostring(
                report_sheet, xml_declaration=True, encoding="UTF-8"
            )
            override = etree.SubElement(content_types, f"{{{content_ns}}}Override")
            override.set("PartName", "/" + printer_path)
            override.set(
                "ContentType",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.printerSettings",
            )
        parts["[Content_Types].xml"] = etree.tostring(
            content_types, xml_declaration=True, encoding="UTF-8"
        )
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()

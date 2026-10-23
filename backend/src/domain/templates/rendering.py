from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import JsonValue
from templexl import Book, TemplateError

from domain.templates.catalog import TemplateCatalog
from domain.templates.printing import preserve_printer_settings


class TemplateInputError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("템플릿 입력값 오류")
        self.errors = errors


class TemplateRenderError(RuntimeError):
    pass


class TemplateRenderer:
    def __init__(self, catalog: TemplateCatalog) -> None:
        self._catalog = catalog

    def render(self, code: str, version: str, data: dict[str, JsonValue]) -> bytes:
        metadata = self._catalog.get(code, version)
        template = self._catalog.file(code, version)
        validator = Draft202012Validator(metadata.variables, format_checker=FormatChecker())
        errors = [
            {"loc": ["body", "data", *error.absolute_path], "msg": error.message}
            for error in validator.iter_errors(data)
        ]
        if errors:
            raise TemplateInputError(errors)
        properties = cast(dict[str, dict[str, Any]], metadata.variables["properties"])
        values: dict[str, Any] = {}
        for name, value in data.items():
            schema = properties[name]
            if schema.get("type") == "array":
                values[name] = pd.DataFrame(value, columns=metadata.tables[name])
            else:
                values[name] = value
        try:
            with TemporaryDirectory(prefix="gyeonggi-report-") as directory:
                book = Book(template)
                try:
                    result = book.render(values)
                    if result.warnings:
                        raise TemplateRenderError("템플릿 변수 치환 누락")
                    # Excel의 자동 높이 조정 방지를 위한 템플릿 기본 높이 명시
                    for sheet in book.workbook.worksheets:
                        for row_number in range(1, sheet.max_row + 1):
                            dimension = sheet.row_dimensions[row_number]
                            if dimension.height is None:
                                dimension.height = sheet.sheet_format.defaultRowHeight
                    output = Path(directory) / "report.xlsx"
                    book.save(output)
                    return preserve_printer_settings(template, output.read_bytes())
                finally:
                    book.close()
        except TemplateError as error:
            raise TemplateRenderError("Excel 보고서 생성 실패") from error

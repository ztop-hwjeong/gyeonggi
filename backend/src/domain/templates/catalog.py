from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from jsonschema import Draft202012Validator

from domain.templates.models import TemplateVersion


class TemplateNotFoundError(LookupError):
    pass


class TemplateCatalog:
    def __init__(self, directory: Path) -> None:
        self._versions: dict[tuple[str, str], tuple[TemplateVersion, Path]] = {}
        if not directory.is_dir():
            raise ValueError(f"템플릿 디렉터리 없음: {directory}")
        for manifest in sorted(directory.glob("*/*/manifest.json")):
            metadata = TemplateVersion.model_validate_json(manifest.read_bytes())
            Draft202012Validator.check_schema(metadata.variables)
            if metadata.variables.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                raise ValueError(f"JSON Schema Draft 2020-12 선언 필요: {manifest}")
            if metadata.variables.get("type") != "object":
                raise ValueError(f"템플릿 변수는 object 스키마 필요: {manifest}")
            properties = metadata.variables.get("properties")
            if not isinstance(properties, dict):
                raise ValueError(f"템플릿 변수의 properties 필요: {manifest}")
            array_names = set()
            for name, schema in properties.items():
                if isinstance(schema, dict) and schema.get("type") == "array":
                    array_names.add(name)
                    items = schema.get("items")
                    if not isinstance(items, dict) or items.get("type") != "object":
                        raise ValueError(f"표 변수는 object 항목 스키마 필요: {manifest}")
                    fields = items.get("properties")
                    if not isinstance(fields, dict):
                        raise ValueError(f"표 변수의 항목 properties 필요: {manifest}")
                    columns = metadata.tables.get(name, ())
                    if set(columns) != set(fields) or len(set(columns)) != len(columns):
                        raise ValueError(f"표의 필드 순서와 입력 스키마 불일치: {manifest}")
            if array_names != set(metadata.tables):
                raise ValueError(f"표 변수와 표 정의 불일치: {manifest}")
            if (manifest.parent.parent.name, manifest.parent.name) != (
                metadata.code,
                metadata.version,
            ):
                raise ValueError(f"템플릿 코드·버전과 경로 불일치: {manifest}")
            file = manifest.parent / metadata.filename
            if sha256(file.read_bytes()).hexdigest() != metadata.sha256:
                raise ValueError(f"템플릿 파일 해시 불일치: {file}")
            with ZipFile(file) as workbook:
                root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
            sheets = root.findall("{*}sheets/{*}sheet")
            if [sheet.get("name") for sheet in sheets] != [s.name for s in metadata.sheets]:
                raise ValueError(f"템플릿 시트 구성 불일치: {file}")
            if len({s.code for s in metadata.sheets}) != len(metadata.sheets):
                raise ValueError(f"템플릿 시트 코드 중복: {manifest}")
            self._versions[metadata.code, metadata.version] = metadata, file
        if not self._versions:
            raise ValueError(f"등록된 템플릿 없음: {directory}")

    def list_versions(self, code: str | None = None) -> list[TemplateVersion]:
        return [
            metadata
            for metadata, _ in self._versions.values()
            if code is None or metadata.code == code
        ]

    def get(self, code: str, version: str) -> TemplateVersion:
        return self._find(code, version)[0]

    def file(self, code: str, version: str) -> Path:
        return self._find(code, version)[1]

    def _find(self, code: str, version: str) -> tuple[TemplateVersion, Path]:
        try:
            return self._versions[code, version]
        except KeyError:
            raise TemplateNotFoundError(f"템플릿 버전 없음: {code}/{version}") from None

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from domain.templates.catalog import TemplateCatalog
from domain.templates.models import TemplateReference


class TemplateArchive:
    def __init__(self, catalog: TemplateCatalog) -> None:
        self._catalog = catalog

    def build(self, templates: tuple[TemplateReference, ...]) -> bytes:
        entries = [
            (
                self._catalog.get(item.code, item.version),
                self._catalog.file(item.code, item.version),
            )
            for item in templates
        ]
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for metadata, file in entries:
                directory = f"{metadata.code}/{metadata.version}"
                archive.write(file, arcname=f"{directory}/{metadata.filename}")
                archive.writestr(
                    f"{directory}/manifest.json",
                    metadata.model_dump_json(indent=2).encode("utf-8"),
                )
        return buffer.getvalue()

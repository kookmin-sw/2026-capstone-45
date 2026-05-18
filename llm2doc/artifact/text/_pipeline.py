import rhwp
import codecs

from chardet import UniversalDetector, EncodingEra
from markitdown import MarkItDown

from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.artifact.ocr import OCRArtifactPipeline
from llm2doc.artifact.text._artifact import TextArtifact
from llm2doc.context.document import DocumentContext


class TextArtifactPipeline(ArtifactPipeline[TextArtifact]):
    ARTIFACT = TextArtifact
    ARTIFACT_NAME = "TextArtifact"
    INPUT_ARTIFACTS = ["OCRArtifact"]

    def __init__(self, ctx):
        super().__init__(ctx)
        self.markitdown = MarkItDown()

    def process(self, document) -> TextArtifact:
        ocr = document.get_artifact(OCRArtifactPipeline)
        if len(ocr.pages) != 0:
            return self._process_ocr(document)
        elif document.doc_ext == "pdf":
            return self._process_pdf(document)
        elif document.doc_ext in ("doc", "docx"):
            return self._process_msword(document)
        elif document.doc_ext in ("hwp", "hwpx"):
            return self._process_hancom(document)
        elif document.doc_ext in ("txt", "md", "htm", "html"):
            return self._process_plain_text(document)
        else:
            raise RuntimeError(f"Unknown file type: {document.doc_ext}")

    def _process_ocr(self, document: DocumentContext) -> TextArtifact:
        ocr = document.get_artifact(OCRArtifactPipeline)
        return TextArtifact(content_markdown=ocr.concatenated_markdown)

    def _process_pdf(self, document: DocumentContext) -> TextArtifact:
        result = self.markitdown.convert_local(document.original_file_path, file_extension=document.doc_ext)
        return TextArtifact(content_markdown=result.markdown)

    def _process_msword(self, document: DocumentContext) -> TextArtifact:
        result = self.markitdown.convert_local(document.original_file_path, file_extension=document.doc_ext)
        return TextArtifact(content_markdown=result.markdown)

    def _process_hancom(self, document: DocumentContext) -> TextArtifact:
        result = rhwp.parse(document.original_file_path)
        return TextArtifact(content_markdown=result.extract_text())

    def _process_plain_text(self, document: DocumentContext) -> TextArtifact:
        det = UniversalDetector(encoding_era=EncodingEra.MODERN_WEB, prefer_superset=True, compat_names=False)
        with open(document.original_file_path, "rb") as f:
            while True:
                buf = f.read(4096)
                if len(buf) == 0:
                    break

                det.feed(buf)
                if det.done:
                    break

        if det.result["encoding"] is None:
            with open(document.original_file_path, mode="rt", encoding="cp1252", errors="ignore") as f:
                return TextArtifact(content_markdown=f.read())
        else:
            with open(document.original_file_path, mode="rt", encoding=det.result["encoding"]) as f:
                return TextArtifact(content_markdown=f.read())

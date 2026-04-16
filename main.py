import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from code.generation.generation_types import GenerationConfig
from code.reference_pipeline import parse_reference
from code.render_pipeline import render_generated_document
from code.semantic_types import SemanticConfig
from code.generation_pipeline import generate_document


Step = Literal["parse", "generate", "render", "pipeline"]


@dataclass
class RunnerPreset:
    name: str
    reference_job_id: str
    reference: str
    source_artifact_dir: str
    generation_job_id: str
    render_output_dir: str
    ocr_source: str = "llm2doc"
    artifacts_root: str = "artifacts"
    ocr_results_root: str = "OCR_results"
    llm2doc_root: str = "llm-to-document"
    reference_source: str | None = None
    semantic: SemanticConfig | None = None
    generation: GenerationConfig | None = None


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# 미리 정의한 preset을 쓸지, 아래 직접 입력값을 바로 쓸지 선택합니다.
USE_PRESET = False

# 평소에는 이 두 값만 바꿔서 실행하면 됩니다.
ACTIVE_PRESET = "combined_fin_render"
ACTIVE_STEP: Step = "render"

# 직접 입력 모드:
# USE_PRESET = False로 바꾸고 아래 값들을 수정하면
# 새 preset을 추가하지 않고도 원하는 파일/아티팩트로 바로 실행할 수 있습니다.

# parse 단계에서 reference artifact를 저장할 job 이름입니다.
REFERENCE_JOB_ID = "financial2-00"
# parse 단계에서 읽을 기준 문서 id 또는 샘플 이름입니다.
REFERENCE = "financial2"

# generate 단계에서 사용할 source artifact 디렉터리입니다.
SOURCE_ARTIFACT_DIR = "artifacts/combined_fin/01_reference"
# generate 단계 결과가 저장될 job 이름입니다.
GENERATION_JOB_ID = "combined_fin"

# render 단계 결과 이미지와 manifest를 저장할 출력 디렉터리입니다.
RENDER_OUTPUT_DIR = "generate_fin"
# reference 파싱에 사용할 OCR 입력 소스입니다. precomputed 또는 llm2doc를 사용합니다.
OCR_SOURCE = "llm2doc"

# 전체 artifact가 저장되는 루트 디렉터리입니다.
ARTIFACTS_ROOT = "artifacts"

# OCR_SOURCE=precomputed일 때 사용할 OCR_results 루트 디렉터리입니다.
OCR_RESULTS_ROOT = "OCR_results"
# OCR_SOURCE=llm2doc 또는 render 단계에서 사용할 llm-to-document 루트 디렉터리입니다.
LLM2DOC_ROOT = "llm-to-document"

# render 단계에서 원본 reference 페이지 이미지가 들어 있는 폴더 또는 파일 경로입니다.
REFERENCE_SOURCE = "llm-to-document/data/financial2"

# 이 설정들은 preset 모드와 직접 입력 모드에서 공통으로 사용합니다.
DEFAULT_SEMANTIC_CONFIG = SemanticConfig(
    mode="qwen",
    model_name="Qwen/Qwen3.5-9B",
    runtime="api",
    device="auto",
)

DEFAULT_GENERATION_CONFIG = GenerationConfig(
    mode="qwen",
    model_name="Qwen/Qwen3.5-9B",
    runtime="api",
    device="auto",
)


PRESETS: dict[str, RunnerPreset] = {
    "combined_fin_render": RunnerPreset(
        name="combined_fin_render",
        reference_job_id="financial2-00",
        reference="financial2",
        source_artifact_dir="artifacts/combined_fin/01_reference",
        generation_job_id="combined_fin",
        render_output_dir="generate_fin",
        ocr_source="precomputed",
        reference_source="llm-to-document/data/financial2",
        semantic=DEFAULT_SEMANTIC_CONFIG,
        generation=DEFAULT_GENERATION_CONFIG,
    ),
    "financial2_full": RunnerPreset(
        name="financial2_full",
        reference_job_id="financial2-00",
        reference="financial2",
        source_artifact_dir="artifacts/combined_fin/01_reference",
        generation_job_id="generate_fin",
        render_output_dir="generate_fin",
        ocr_source="llm2doc",
        reference_source="llm-to-document/data/financial2",
        semantic=DEFAULT_SEMANTIC_CONFIG,
        generation=DEFAULT_GENERATION_CONFIG,
    ),
}


def _abs(path: str | None) -> str | None:
    if path is None:
        return None
    return str((PROJECT_ROOT / path).resolve())


def _require_preset(name: str) -> RunnerPreset:
    if name not in PRESETS:
        raise KeyError(
            f"unknown preset: {name}. available presets: {', '.join(sorted(PRESETS))}"
        )
    return PRESETS[name]


def _build_direct_runner() -> RunnerPreset:
    # 위에 적어둔 직접 입력값으로 임시 RunnerPreset을 만듭니다.
    # 실행 로직은 preset 방식과 동일하게 유지하면서, 경로만 자유롭게 바꾸려는 목적입니다.
    return RunnerPreset(
        name="direct_input",
        reference_job_id=REFERENCE_JOB_ID,
        reference=REFERENCE,
        source_artifact_dir=SOURCE_ARTIFACT_DIR,
        generation_job_id=GENERATION_JOB_ID,
        render_output_dir=RENDER_OUTPUT_DIR,
        ocr_source=OCR_SOURCE,
        artifacts_root=ARTIFACTS_ROOT,
        ocr_results_root=OCR_RESULTS_ROOT,
        llm2doc_root=LLM2DOC_ROOT,
        reference_source=REFERENCE_SOURCE,
        semantic=DEFAULT_SEMANTIC_CONFIG,
        generation=DEFAULT_GENERATION_CONFIG,
    )


def run_parse(preset: RunnerPreset) -> dict:
    # 기준 문서를 파싱해서 downstream 단계에서 쓰는 reference artifact를 생성합니다.
    semantic_config = preset.semantic or SemanticConfig()
    return parse_reference(
        job_id=preset.reference_job_id,
        reference_path=preset.reference,
        artifacts_root=_abs(preset.artifacts_root),
        ocr_source=preset.ocr_source,
        ocr_results_root=_abs(preset.ocr_results_root),
        llm2doc_root=_abs(preset.llm2doc_root),
        semantic_config=semantic_config,
    )


def run_generate(preset: RunnerPreset) -> dict:
    # 이미 만들어진 reference artifact와 source artifact를 사용해 새 문서 내용을 생성합니다.
    generation_config = preset.generation or GenerationConfig()
    return generate_document(
        job_id=preset.generation_job_id,
        reference_artifact_dir=_abs(f"{preset.artifacts_root}/{preset.reference_job_id}/01_reference"),
        source_artifact_dir=_abs(preset.source_artifact_dir),
        artifacts_root=_abs(preset.artifacts_root),
        generation_config=generation_config,
    )


def run_render(preset: RunnerPreset) -> dict:
    # 생성된 slot 텍스트를 기준 문서 페이지 이미지 위에 다시 렌더링합니다.
    return render_generated_document(
        reference_artifact_dir=_abs(f"{preset.artifacts_root}/{preset.reference_job_id}/01_reference"),
        generation_artifact_dir=_abs(f"{preset.artifacts_root}/{preset.generation_job_id}/02_generation"),
        llm2doc_root=_abs(preset.llm2doc_root),
        output_dir=_abs(preset.render_output_dir),
        reference_source=_abs(preset.reference_source),
    )


def main() -> None:
    # preset 방식 또는 직접 입력 방식 중 하나를 골라 실행 대상을 결정합니다.
    preset = _require_preset(ACTIVE_PRESET) if USE_PRESET else _build_direct_runner()

    print(
        json.dumps(
            {
                "use_preset": USE_PRESET,
                "active_preset": preset.name,
                "active_step": ACTIVE_STEP,
                "project_root": str(PROJECT_ROOT),
                "preset": asdict(preset),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if ACTIVE_STEP == "parse":
        result = run_parse(preset)
    elif ACTIVE_STEP == "generate":
        result = run_generate(preset)
    elif ACTIVE_STEP == "render":
        result = run_render(preset)
    elif ACTIVE_STEP == "pipeline":
        result = {
            "parse": run_parse(preset),
            "generate": run_generate(preset),
            "render": run_render(preset),
        }
    else:
        raise ValueError(f"unsupported step: {ACTIVE_STEP}")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

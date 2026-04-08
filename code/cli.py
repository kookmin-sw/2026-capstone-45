import argparse
import json
from dotenv import load_dotenv

from .generation_pipeline import generate_document
from .generation_types import GenerationConfig
from .reference_pipeline import parse_reference
from .semantic_types import SemanticConfig
from .visualize import render_reference_visualization

# .env 파일 로드
load_dotenv()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="allm")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_reference_parser = subparsers.add_parser("parse-reference", help="Build a reference template from OCR outputs")
    parse_reference_parser.add_argument("--job-id", required=True)
    parse_reference_parser.add_argument("--reference", required=True)
    parse_reference_parser.add_argument("--artifacts-root", default="artifacts")
    parse_reference_parser.add_argument("--ocr-results-root", default="OCR_results")
    parse_reference_parser.add_argument("--semantic-mode", choices=["rule", "qwen", "shadow"], default="qwen")
    parse_reference_parser.add_argument("--semantic-model", default="Qwen/Qwen3.5-9B")
    parse_reference_parser.add_argument("--semantic-runtime", choices=["transformers", "api"], default="api")
    parse_reference_parser.add_argument("--semantic-device", default="auto")

    visualize_parser = subparsers.add_parser("visualize-reference", help="Render an HTML visualization for a reference artifact")
    visualize_parser.add_argument("--artifact-dir", required=True)
    visualize_parser.add_argument("--output", default=None)
    visualize_parser.add_argument("--reference-source", default=None)

    generate_parser = subparsers.add_parser("generate-document", help="Generate a new document from a reference artifact and source artifact")
    generate_parser.add_argument("--job-id", required=True)
    generate_parser.add_argument("--reference-artifact-dir", required=True)
    generate_parser.add_argument("--source-artifact-dir", required=True)
    generate_parser.add_argument("--artifacts-root", default="artifacts")
    generate_parser.add_argument("--generation-mode", choices=["rule", "qwen"], default="qwen")
    generate_parser.add_argument("--generation-model", default="Qwen/Qwen3.5-9B")
    generate_parser.add_argument("--generation-runtime", choices=["transformers", "api"], default="api")
    generate_parser.add_argument("--generation-device", default="auto")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "parse-reference":
        semantic_config = SemanticConfig(
            mode=args.semantic_mode,
            model_name=args.semantic_model,
            runtime=args.semantic_runtime,
            device=args.semantic_device,
        )
        result = parse_reference(
            job_id=args.job_id,
            reference_path=args.reference,
            artifacts_root=args.artifacts_root,
            ocr_results_root=args.ocr_results_root,
            semantic_config=semantic_config,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "visualize-reference":
        output = render_reference_visualization(
            artifact_dir=args.artifact_dir,
            output_path=args.output,
            reference_source=args.reference_source,
        )
        print(json.dumps({"html": output}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "generate-document":
        generation_config = GenerationConfig(
            mode=args.generation_mode,
            model_name=args.generation_model,
            runtime=args.generation_runtime,
            device=args.generation_device,
        )
        result = generate_document(
            job_id=args.job_id,
            reference_artifact_dir=args.reference_artifact_dir,
            source_artifact_dir=args.source_artifact_dir,
            artifacts_root=args.artifacts_root,
            generation_config=generation_config,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

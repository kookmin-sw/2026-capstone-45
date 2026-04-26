# llm2doc 통합 설계서

## 요약
이 문서는 `C:\Users\echin\Desktop\ALLLM\llm-to-document\llm2doc`를 기준 패키지로 유지하면서, `C:\Users\echin\Desktop\ALLLM\0. llm2doc 백업`의 확장 기능을 단계적으로 흡수하기 위한 통합 계획서다.

핵심 원칙은 다음과 같다.

- 메인 기준은 현재 `llm-to-document/llm2doc`다.
- 백업본은 기능 공급원이며, 전체 덮어쓰기는 금지한다.
- 최종 엔트리포인트는 `llm2doc.create_document.create_document` 하나로 통일한다.
- `semantic_pipeline`은 현재 유지 대상이 아니라, 백업본에서 소스를 복구한 뒤 현재 구조에 맞게 재배치하는 선행 과제다.

현재 확인된 실제 상태:

- 현재 `llm2doc/semantic_pipeline`에는 하위 디렉터리만 있고 실제 `.py` 소스는 없으며 `__pycache__`만 남아 있다.
- 현재 `create_document.py`와 `tool_search_source_document.py`는 단순 버전이다.
- 백업본의 `create_document.py`와 `tool_search_source_document.py`는 output/trace/semantic-aware retrieval까지 포함한 확장 버전이다.
- 현재 `render_image.py`는 렌더 품질 문제가 있으며, 별도 하위 과제로 다루는 것이 맞다.

## 통합 원칙
통합은 "현재 코드 유지 + 백업 기능 이식" 방식으로 진행한다.

- 현재 `llm2doc`의 import 경로와 실행 구조를 기준으로 한다.
- 백업 폴더 전체 복사, 통째 덮어쓰기, 경로 하드코딩 유지 방식은 사용하지 않는다.
- 기능 단위로 이식하고, 각 단계마다 import/실행/산출물 기준을 고정한다.
- 실험 코드나 비교 구현은 필요하면 `legacy`, `plain`, `backup` 성격으로 명시적으로 남긴다.

## 통합 대상과 주도권
### 백업본 기준으로 가져올 파일
- `create_document.py`
- `tool_search_source_document.py`
- `debug_trace.py`
- `bm25_search.py`
- `semantic_pipeline` 소스 전체

### 현재본 기준으로 유지할 파일
- `analyze_layout.py`
- `render_image.py`
- `tool_fetch_source_document.py`
- `util.py`

### 유지 이유
- `analyze_layout.py`는 현재 repo의 OCR/layout 흐름과 직접 연결되어 있다.
- `render_image.py`는 현재 렌더 경로의 기준 구현이며, 완전 교체보다 부분 개선이 안전하다.
- `tool_fetch_source_document.py`는 현재 구조와 거의 일치하며, 백업본의 검증 보강만 반영하면 충분하다.
- `util.py`는 현재 경량 유틸 기준을 유지하는 편이 안전하다.

## 0단계: semantic_pipeline 복구
현재 `llm2doc/semantic_pipeline`는 소스가 없는 상태이므로, 통합의 첫 단계는 복구다.

복구 대상:

- `reference_pipeline.py`
- `semantic_types.py`
- `visualize.py`
- `analysis/*`
- `common/*`
- `parsing/*`
- `pipeline/*`
- `semantic/*`

복구 방식:

- 백업본의 `semantic_pipeline`에서 `.py` 소스만 가져온다.
- `__pycache__`, `.pyc`는 제외한다.
- 현재 repo 기준 import 경로로 정리한다.
- public surface는 다음 기준으로 복구한다.
  - `parse_reference(...)`
  - `build_reference_template(...)`
  - `render_reference_visualization(...)`
  - `SemanticConfig`

복구 완료 기준:

- `llm2doc.semantic_pipeline`에서 위 public API import 가능
- `compileall` 통과
- `parse_reference(...)` 단독 실행 가능

## 1단계: 검색기 통합
현재 `ToolSearchSourceDocument`는 단순 Chroma vector search 기반이다. 이를 백업본 기준의 hybrid retrieval 구조로 교체한다.

변경되는 기능:

- semantic artifact 기반 검색 추가
- BM25 채널 추가
- entity grounding 추가
- first-stage candidate aggregation 추가
- candidate reorder/score 조정 추가
- trace 가능한 검색 단계 추가

삭제되거나 주 경로에서 내려오는 기능:

- OCR block만 임베딩해서 top-k만 반환하는 단일 검색 경로
- semantic artifact 없는 상태를 기본 경로로 가정하는 구조

유지할 인터페이스:

- 클래스명 `ToolSearchSourceDocument`
- tool name `search_source_document`
- `invoke(...)`, `invoke_raw(...)` 중심 호출 방식

통합 시 주의점:

- `semantic_pipeline` artifact 경로는 현재 repo의 `output/<run_name>/semantic_artifacts/...` 기준으로 맞춘다.
- 백업본의 하드코딩 `artifacts` 경로는 그대로 사용하지 않는다.
- 기존 간단 검색 구현은 필요하면 `tool_search_source_document_plain.py` 성격으로 보존한다.

## 2단계: create_document 통합
현재 `create_document.py`는 단순 실행형 오케스트레이터다. 백업본의 파이프라인형 구조를 현재 파일에 반영한다.

추가되는 기능:

- output 디렉터리 생성 및 run 단위 결과 분리
- trace 디렉터리 생성
- semantic artifact 자동 생성
- semantic visualization 생성
- final `<document>` 블록 검증
- final document 재시도 로직
- 결과 파일 경로 출력

변경되는 동작:

- 현재처럼 cwd에 `debug_write_*`, `debug_finish_*.png`를 바로 생성하는 방식에서
- `output/<run_name>/...` 아래로 산출물을 모으는 방식으로 변경

비활성 유지할 기능:

- `tool_ask_user_question` 기반 사용자 질의 유도 흐름

삭제되거나 폐기되는 설계:

- semantic artifact를 미리 만들지 않고 검색만 수행하는 구조
- final output 검증 없이 첫 응답을 바로 렌더하는 구조
- cwd 산출물 기준 운영 방식

유지할 public API:

- `llm2doc.create_document.create_document`

유지할 호환성:

- `generate-document.py`의 `from llm2doc.create_document import create_document` import는 그대로 유지
- `data/<doc>` 기반 입력 구조는 그대로 유지

## 3단계: fetch 도구 보강
`tool_fetch_source_document.py`는 현재 구현을 유지하고, 백업본의 검증만 반영한다.

유지되는 기능:

- `document_id`, `page_id` 기반 페이지 HTML fetch
- `ParsedDocument`를 입력으로 받는 구조

추가되는 기능:

- `page_id` 정수 검증
- `page_id` 범위 검증 메시지 개선

삭제되는 기능:

- 없음

## 4단계: render_image 정리
렌더는 현재 파일을 기준으로 유지하되, 통합 1차 완료 후 별도 하위 작업으로 개선한다.

현 상태 문제:

- 기본 폰트 경로가 깨져 있을 수 있음
- Skia ICU 환경 경고가 있음
- HTML/table 렌더 경로가 부분 비활성화 상태
- 텍스트 렌더가 실제로 픽셀을 만들지 못하는 문제가 재현됨

향후 반영 후보:

- 백업본의 font stack 방식
- 백업본의 text-fit 로직
- HTML/table 렌더 활성화

유지되는 기능:

- 현재 렌더 함수 시그니처와 전체 흐름

삭제되지 않는 이유:

- 현재 `analyze_layout.py`와 가장 잘 결합된 렌더 기준 구현이기 때문

## 경로 및 산출물 규칙
모든 산출물은 repo 루트 기준 `output/<run_name>/...` 아래로 통일한다.

구조:

- `output/<run_name>/debug_write_input.txt`
- `output/<run_name>/debug_write_input.json`
- `output/<run_name>/debug_write_output.txt`
- `output/<run_name>/debug_write_reason.txt`
- `output/<run_name>/debug_finish_*.png`
- `output/<run_name>/trace/...`
- `output/<run_name>/semantic_artifacts/<doc>-00/01_reference/...`

금지 규칙:

- cwd 산출물 직접 저장 금지
- 백업본 하드코딩 절대경로 유지 금지

## 변경/삭제 요약
### 변경되는 기능
- `create_document`: output/trace/artifact 기반 파이프라인으로 변경
- `search_source_document`: hybrid retrieval 기반으로 변경
- `tool_fetch_source_document`: 검증 보강
- `semantic_pipeline`: 복구 후 파싱/semantic/visualization 기능 제공
- `render_image`: 현재 구조 유지, 후속 개선 대상으로 분리

### 삭제되거나 폐기되는 기능
- 단일 vector-search 중심 검색 구조
- semantic artifact 없는 경로를 기본 검색 경로로 쓰는 방식
- cwd에 결과를 직접 쓰는 출력 방식
- `semantic_pipeline`를 pycache 상태로 방치한 채 import만 맞추는 방식

### 비활성 유지되는 기능
- `tool_ask_user_question` 기반 사용자 질의 흐름
- 비교용 legacy/experimental 경로가 있다면 보조 구현으로만 유지

## 테스트 계획
### semantic_pipeline 복구 확인
- `.py` 소스 실제 존재 확인
- `parse_reference`, `render_reference_visualization`, `SemanticConfig` import smoke test
- `compileall` on `llm2doc.semantic_pipeline`

### 검색 회귀 테스트
- semantic artifact 있음/없음 모두 검색 결과 반환 확인
- source 1개 / source 여러 개 케이스 확인

### 오케스트레이션 회귀 테스트
- `create_document(query, ['news1'], 'financial2')` 실행 시:
  - output dir 생성
  - semantic_artifacts 생성
  - trace 생성
  - debug files 저장
  - final document parsing 성공

### 렌더 회귀 테스트
- 최소 1개 텍스트 블록이 실제 픽셀로 렌더되는지 확인
- HTML/table block 렌더 활성화 여부 확인

### 정적 검증
- `compileall` on `llm2doc`
- circular import 없음 확인

## 가정
- 이 문서는 구현이 아니라 실제 작업자가 바로 따라갈 수 있는 통합 설계서다.
- 현재 `semantic_pipeline`는 유지 대상이 아니라 복구 대상이다.
- 1차 통합의 중심은 `create_document + tool_search_source_document + semantic_pipeline 복구`다.
- 렌더 품질 복구는 통합 범위에 포함되지만 별도 하위 과제로 다룬다.
- `ask_user_question`는 당분간 비활성 상태를 유지한다.

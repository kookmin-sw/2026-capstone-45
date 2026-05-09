[![Review Assignment Due Date](https://classroom.github.com/assets/deadline-readme-button-22041afd0340ce965d47ae6ef1cefeee28c7c493a6346c4f15d667ab976d596c.svg)](https://classroom.github.com/a/Lvs6kcL8)
# LLM 기반 지정문서 생성 시스템

## 1. 프로젝트 소개

본 프로젝트는 사용자가 지정한 대상 문서의 시각적 레이아웃, 글꼴 서식, 논리적 구조를 그대로 보존한 상태에서 사용자의 요구사항과 참고 문서의 내용을 바탕으로 새로운 문서를 자동 생성하는 에이전틱 시스템입니다.

### 주요 기능 및 특징
- 서식 및 레이아웃 보존: PaddleOCR과 Tesseract, 자체 폰트 분석기를 결합하여 원본 문서의 위치 배열 및 스타일을 정밀하게 추출합니다.
- 의미론적 문서 분석: Qwen LLM을 활용해 문서 내 텍스트 블록들의 역할(제목, 본문, 메타데이터 등)을 분석하고 스키마로 구조화합니다.
- OCR 기반 문서 분석: 스크린샷으로 되어있는 문서도 처리할 수 있습니다.
- 에이전트 기반 정보 처리: 새 문서를 생성하기 위해 LLM 에이전트(OpenAI)가 자체적으로 도구를 호출하여 참고 문서를 검색(Semantic + BM25 하이브리드 검색)하고 필요한 정보를 수집하여 내용을 합성합니다.
- Web UI: React와 기반의 인터페이스를 통해 시스템을 사용할 수 있습니다.

### 문서 처리 및 생성 워크플로우
시스템에 문서가 업로드되어 새로운 문서가 생성되기까지 다음과 같은 일련의 과정을 거칩니다.

1. 문서 전처리: 문서가 업로드되면 OCR을 통해 텍스트 위치와 레이아웃을 추출하고, 폰트 및 시각적 속성을 분석하며, LLM을 이용해 각 텍스트 블록의 역할과 문서의 논리적 스키마를 파악합니다.
2. 데이터 색인: 분석이 완료된 문서는 메타데이터 및 구조 정보와 함께 저장되어 이후 '참고 문서'로 활용될 수 있는 상태가 됩니다.
3. 대상 문서 지정: 사용자는 시스템에 등록된 문서 중 하나를 선택하여 서식과 구조를 따라할 '대상 문서'로 지정합니다.
4. 에이전트 기반 컨텐츠 생성: 사용자가 새 문서 생성을 요청하면, AI 에이전트가 대상 문서의 시맨틱 스키마를 바탕으로 채워 넣을 내용을 계획합니다. 이때 에이전트는 도구를 사용해 DB에 저장된 다른 참고 문서들을 검색 및 조회하여 요구사항에 맞는 내용을 작성합니다.
5. 최종 렌더링: 에이전트가 생성한 텍스트 내용과 대상 문서에서 추출했던 위치/폰트/스타일 정보를 결합하여, 원본과 동일한 양식을 가진 새로운 문서가 시각적으로 렌더링됩니다.

## 2. 소개 영상

(추가예정)

## 3. 팀 소개

(팀원 정보, 역할 분담, 사진 및 SNS 등을 여기에 추가하세요.)

## 4. 사용법

### 배포환경 실행 방법

Docker Compose를 이용하면 백엔드, 프론트엔드, AI 모델 서버(PaddleOCR-VL 등)를 한 번에 간편하게 실행할 수 있습니다.

1. 사전 준비사항
- Docker
- NVidia GPU

2. 환경변수 세팅

루트 디렉토리에 `.env` 파일 생성 후 필요한 API 키를 입력합니다.
```ini
OPENAI_API_KEY=your_api_key_here
OPENAI_LITE_API_KEY=your_lite_api_key_here
OPENAI_EMBED_API_KEY=your_embed_api_key_here
```

BASE_URL은 기본적으로 OpenRouter를 향하도록 되어있습니다.
변경할 필요가 있을 경우 마찬가지로 `.env`파일에 입력합니다.
호스트에 접속하도록 세팅할때는 `localhost` 대신 `host.docker.internal`를 입력합니다.
```ini
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_LITE_BASE_URL=https://openrouter.ai/api/v1
OPENAI_EMBED_BASE_URL=https://openrouter.ai/api/v1
```

사용할 모델을 변경할 필요가 있을 경우 마찬가지로 `.env`파일에 입력합니다.
```ini
OPENAI_MODEL=qwen/qwen3.5-397b-a17b
OPENAI_LITE_MODEL=openai/gpt-oss-20b
OPENAI_EMBED_MODEL=qwen/qwen3-embedding-8b
```

3. 실행
```bash
docker compose up -d
```

모든 컨테이너가 정상적으로 실행되면 `http://localhost:5000`으로 접속하여 Web UI를 이용할 수 있습니다.

4. 종료
```bash
docker compose down
```

### 개발환경 세팅 방법

1. 사전 준비사항
- Python 3.12 이상
- [uv 패키지 관리자](https://docs.astral.sh/uv/#installation)
- [pnpm 패키지 관리자](https://pnpm.io/ko/installation)

2. 저장소 클론:
```bash
git clone https://github.com/jsonmona/llm2doc.git
cd llm2doc
```

3. 백엔드 의존성 설치 (uv 사용):

NVidia GPU가 있는 경우:
```bash
uv sync --extra cuda
```

NVidia GPU가 없는 경우:
```bash
uv sync --extra cpu
```

4. 프론트엔드 의존성 설치:
```bash
cd web
pnpm install
```

### 개발환경 실행 방법

서버와 클라이언트를 각각 실행해야 합니다.

**1. 서버 실행 (백엔드)**
루트 디렉토리(`llm2doc/`)에서 아래 명령어를 실행합니다.
```bash
fastapi dev
```

**2. 웹 클라이언트 실행 (프론트엔드)**
`web/` 디렉토리에서 아래 명령어를 실행합니다.
```bash
cd web
pnpm dev
```
이후 프론트엔드 터미널에 출력된 URL(예: http://localhost:5173)로 접속하여 웹 UI를 이용할 수 있습니다.

### CLI 도구 사용법

웹 UI 없이 내부 스크립트를 통해 시스템을 테스트할 수도 있습니다.

- **문서 일괄 추가:** `data/` 디렉토리에 위치한 모든 PDF 문서를 처리하여 DB에 등록합니다.
  ```bash
  python add-all-documents.py
  ```
- **문서 생성 테스트:** CLI 환경에서 문서 생성 파이프라인을 실행합니다. 결과물은 `debug_현재시간` 디렉토리에 저장됩니다.
  ```bash
  python generate-document.py
  ```

## 5. 기타

### 아키텍처 및 기술 스택
- Backend: Python, FastAPI, SQLAlchemy, SQLite, ChromaDB
- Frontend: React, Mantine UI, TanStack Query & Router
- AI 파이프라인: PaddleOCR-VL, Tesseract, OpenAI-compatible API

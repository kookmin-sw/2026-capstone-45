# 개발환경 설정법

로컬 환경에서 직접 소스 코드를 실행하고 개발하기 위한 가이드입니다.

## 1. 사전 준비사항
- Python 3.12 이상
- [uv 패키지 관리자](https://docs.astral.sh/uv/#installation)
- [pnpm 패키지 관리자](https://pnpm.io/ko/installation)

## 2. 저장소 클론
```bash
git clone https://github.com/jsonmona/llm2doc.git
cd llm2doc
```

## 3. 백엔드 의존성 설치 (uv 사용)

NVidia GPU가 있는 경우:
```bash
uv sync --extra cuda
```

NVidia GPU가 없는 경우:
```bash
uv sync --extra cpu
```

## 4. 프론트엔드 의존성 설치
```bash
cd web
pnpm install
```

## 5. 개발환경 실행 방법

서버와 클라이언트를 각각 실행해야 합니다.

### 서버 실행 (백엔드)
루트 디렉토리(`llm2doc/`)에서 아래 명령어를 실행합니다.
```bash
fastapi dev
```

### 웹 클라이언트 실행 (프론트엔드)
`web/` 디렉토리에서 아래 명령어를 실행합니다.
```bash
cd web
pnpm dev
```
이후 프론트엔드 터미널에 출력된 URL(예: http://localhost:5173)로 접속하여 웹 UI를 이용할 수 있습니다.

## 6. CLI 도구 사용법

웹 UI 없이 내부 스크립트를 통해 시스템을 테스트할 수도 있습니다.

- **문서 일괄 추가**: `data/` 디렉토리에 위치한 모든 PDF 문서를 처리하여 DB에 등록합니다.
  ```bash
  python add-all-documents.py
  ```
- **문서 생성 테스트**: CLI 환경에서 문서 생성 파이프라인을 실행합니다. 결과물은 `debug_현재시간` 디렉토리에 저장됩니다.
  ```bash
  python generate-document.py
  ```

---
[메인으로 돌아가기](index.md) | [배포환경 설정법](deployment.md)

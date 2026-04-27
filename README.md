2026 캡스톤

# 사전 준비사항
- Python 3.12 이상
- [uv 패키지 관리자](https://docs.astral.sh/uv/#installation)
- [pnpm 패키지 관리자](https://pnpm.io/ko/installation)

# 설치 방법

1. 저장소 클론:
```bash
$ git clone https://github.com/jsonmona/llm2doc.git
$ cd llm2doc
```

2. 의존성 설치 (uv 사용):
```bash
llm2doc/ $ uv sync
```

3. 웹 인터페이스 의존성 설치
```bash
llm2doc/ $ cd web
llm2doc/web/ $ pnpm install --dev
```

# 실행방법

## 간편 CLI 도구

### 문서 추가
```bash
llm2doc/ $ python add-all-documents.py
```

`data/` 디렉토리 안에 있는 모든 PDF 파일을 DB에 등록함.

### 채팅 생성
```bash
llm2doc/ $ python generate-document.py
```

문서를 생성하고 debug_현재날짜 디렉토리에 결과물을 저장함.
다만 이미지로 변환하는 기능은 없으므로 결과 문서를 보려면 webui를 실행시키는 것이 편함.

## WebUI

아래 두 프로그램을 동시에 실행시켜야 함.

서버 - `llm2doc/ $ fastapi dev`

클라이언트 - `llm2doc/web/ $ pnpm dev`

그 이후 클라이언트쪽에 뜬 URL로 접속하면 웹 UI가 뜸.

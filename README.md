2026 캡스톤

# 사전 준비사항
- Python 3.12 이상
- [uv 패키지 관리자](https://docs.astral.sh/uv/#installation)

# 설치 방법

1. 저장소 클론:
```bash
git clone https://github.com/jsonmona/llm-to-document.git
cd llm-to-document
```

2. 의존성 설치 (uv 사용):
```bash
uv sync
```

# 프로그램 목록

## 박스 어노테이션 도구
### 실행
```bash
python image_to_bbox.py
```

### 출력 결과
바운딩 박스는 `bbox.json` 파일에 YOLO 형식으로 저장됨

## 문서 생성
### 준비
.env 파일 생성 후 다음 환경변수 세팅:
```ini
OPENAI_BASE_URL=(사용중인 LLM 라우터 주소)
OPENAI_API_KEY=(API 키)
OPENAI_MODEL=(모델 이름)
```

개발중에는 모델은 qwen-9b와 qwen-27b를 이용했음.
qwen-9b도 얼추 동작하지만 문서를 잘 이해하지 못하는 경향이 있음.

data/financial 디렉토리 생성 후 다음 파일 준비:
* `bbox.json`: 바운딩 박스 JSON
* `original.png`: 레이아웃 참고용 지정문서
* `erased.png`: 박스쪽의 텍스트를 지운 빈 문서
* `target.txt`: 문서를 채울 내용을 넣은 텍스트 파일. 이론상 아무 형식이나 가능하나 프롬프트에는 마크다운으로 명시해 뒀음.

### 실행
```bash
python call_llm.py
```
실행중 `data/financial/rendered.png`에 현재까지 채운 템플릿이 있음.

### 출력 결과
`data/financial/final.png`에 최종 렌더링 결과가 저장됨.

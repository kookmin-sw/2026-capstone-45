# 설치 및 실행 가이드

## 사전 준비사항
- Python 3.12 이상
- [uv 패키지 관리자](https://docs.astral.sh/uv/#installation)

## 설치 방법

1. 저장소 클론:
```bash
git clone https://github.com/jsonmona/llm-to-document.git
cd llm-to-document
```

2. 의존성 설치 (uv 사용):
```bash
uv sync
```

## 프로그램 목록

### 박스 어노테이션 도구
#### 실행
```bash
uv run python image_to_bbox.py
```

#### 출력 결과
바운딩 박스는 `bbox.json` 파일에 YOLO 형식으로 저장됨

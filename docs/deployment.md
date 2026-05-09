# 배포환경 설정법

Docker Compose를 이용하면 백엔드, 프론트엔드, AI 모델 서버(PaddleOCR-VL 등)를 한 번에 간편하게 실행할 수 있습니다.

## 1. 사전 준비사항
- Docker
- NVidia GPU

## 2. 환경변수 세팅

루트 디렉토리에 `.env` 파일 생성 후 필요한 API 키를 입력합니다.
```ini
OPENAI_API_KEY=your_api_key_here
OPENAI_LITE_API_KEY=your_lite_api_key_here
OPENAI_EMBED_API_KEY=your_embed_api_key_here
```

`BASE_URL`은 기본적으로 OpenRouter를 향하도록 되어있습니다.
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

## 3. 실행
```bash
docker compose up -d
```

모든 컨테이너가 정상적으로 실행되면 `http://localhost:5000`으로 접속하여 Web UI를 이용할 수 있습니다.

## 4. 종료
```bash
docker compose down
```

---
[메인으로 돌아가기](index.md) | [개발환경 설정법](development.md)

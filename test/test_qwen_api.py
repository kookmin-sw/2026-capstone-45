import os
from openai import OpenAI
from dotenv import load_dotenv

# .env 파일 로드 (상위 폴더에 있는 경우를 대비하여 경로 설정)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

def test_qwen():
    print("Qwen API 테스트를 시작합니다...")
    
    # 설정값 확인
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL")
    
    print(f"Base URL: {base_url}")
    print(f"Model: {model}")
    # API 키는 보안상 앞뒤 일부만 출력
    if api_key:
        print(f"API Key: {api_key[:5]}...{api_key[-5:]}")
    else:
        print("Error: API Key가 설정되지 않았습니다.")
        return

    client = OpenAI(
        api_key=api_key,
        base_url=base_url
    )

    try:
        print("-" * 30)
        print("응답 대기 중...")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Qwen api로 할 수 있는 일들 설명해줘"}
            ]
        )
        print("-" * 30)
        print("API 응답 성공!")
        print(f"결과: {response.choices[0].message.content}")
        print("-" * 30)
    except Exception as e:
        print("-" * 30)
        print(f"API 호출 중 오류 발생: {str(e)}")
        print("팁: .env 파일의 모델명이나 API 키가 정확한지 확인해 보세요.")
        print("-" * 30)

if __name__ == "__main__":
    test_qwen()

import os
from dotenv import load_dotenv
from openai import OpenAI

def main():
    # 환경 변수 로드 (.env 파일)
    load_dotenv()
    
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("OPENAI_MODEL")

    print(f"[설정 정보]")
    print(f"- Base URL: {base_url}")
    print(f"- Model: {model}")
    print(f"- API Key: {'설정됨 (Hidden)' if api_key else '설정되지 않음'}")
    print("-" * 30)

    if not api_key:
        print("에러: OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
        return

    try:
        # OpenAI 클라이언트 생성
        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

        print("\n[테스트 시작] 모델에 인사말을 보냅니다...")
        
        # 모델 테스트 요청
        response = client.chat.completions.create(
            model=model or "gpt-4o", # 환경변수에 모델이 없으면 기본값 사용
            messages=[
                {"role": "system", "content": "당신은 친절한 AI 어시스턴트입니다. 한국어로 짧고 명확하게 답변해주세요."},
                {"role": "user", "content": "한국의 수도에 대해 설명해줘"}
            ],
            max_tokens=100
        )

        print("\n[테스트 완료] 모델 응답:")
        print(f"> {response.choices[0].message.content}")
        
    except Exception as e:
        print("\n[오류 발생] OpenAI API 호출 중 문제가 발생했습니다:")
        print(e)

if __name__ == "__main__":
    main()

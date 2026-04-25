from dotenv import load_dotenv

from llm2doc.create_document_ver2 import create_document


def main():
    load_dotenv()
    option = 1

    if option == 0:
        create_document(None, ["financial2"], "financial1")
    elif option == 1:
        create_document(
            "financial2 문서를 기반으로 KMW 기업 분석 보고서를 작성해줘",
            ["financial2","financial3"],
            "financial1",
        )
    elif option == 2:
        create_document(
            "삼성전자 관련 데일리 브리핑을 작성해줘 (시장 전체 말고 삼성전자만)",
            ["blog1", "financial1", "financial3"],
            "financial2",
        )


if __name__ == "__main__":
    main()

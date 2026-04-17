from dotenv import load_dotenv
from llm2doc.create_document import create_document


def main():
    load_dotenv(override=True)
    option = 3

    if option == 0:
        # KMC 레포트 (의도 자동 완성)
        create_document(None, ["financial2"], "financial1")
    elif option == 1:
        create_document("KMW 기업 보고서 작성해", ["financial2", "financial3"], "financial1")
    elif option == 2:
        create_document(
            "삼성전자 관련 데일리 브리핑 작성해 (시장 전체 말고 삼성전자만)",
            ["blog1", "financial1", "financial3"],
            "financial2",
        )
    elif option == 3:
        create_document("이란 전쟁 관련 시황 브리핑 작성해", ["news1"], "financial2")


if __name__ == "__main__":
    main()

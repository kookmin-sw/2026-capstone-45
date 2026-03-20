from dotenv import load_dotenv
from llm2doc.fill_document import fill_document


def main():
    load_dotenv()

    fill_document()


if __name__ == "__main__":
    main()

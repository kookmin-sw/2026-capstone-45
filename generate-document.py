from dotenv import load_dotenv
from llm2doc.create_document import create_document


def main():
    load_dotenv()
    create_document(None, ["financial1"], "financial2")


if __name__ == "__main__":
    main()

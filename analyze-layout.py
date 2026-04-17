import sys

from llm2doc.analyze_layout import populate_cache
from dotenv import load_dotenv


if __name__ == "__main__":
    load_dotenv()

    answer = ""

    for arg in sys.argv:
        if arg == "--no-clear":
            answer = "n"
        if arg == "--clear":
            answer = "y"

    while answer != "y" and answer != "n":
        answer = input("캐시를 초기화 하시겠습니까 (Y/n)? ").strip().lower()
        if answer == "":
            answer = "y"

    populate_cache(answer == "y")

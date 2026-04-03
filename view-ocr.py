from llm2doc.analyze_layout import LayoutAnalyzer


def main():
    layout_analyzer = LayoutAnalyzer()

    parsed = layout_analyzer("news1")

    for i, page in enumerate(parsed.pages):
        image = page.reconstruct_image()
        image.save(f"debug_ocr_{i + 1}.png")

    with open("debug_ocr.json", "wt", encoding="utf-8") as f:
        f.write("[\n")
        for page in parsed.pages:
            f.write(page.json)
            f.write("\n")
        f.write("]\n")


if __name__ == "__main__":
    main()

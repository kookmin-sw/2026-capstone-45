import os

from fontTools.ttLib import TTFont


def get_font_name(font: TTFont):
    name_table = font["name"]

    for record in name_table.names:
        if record.nameID == 4:
            return record.toUnicode()

    ids = [int(record.nameID) for record in name_table.names]

    raise RuntimeError(f"Could not find font name. {ids=}")


class PathToFontFamily:
    def __init__(self):
        self.path_to_font_map: dict[str, str] = dict()
        self.font_to_path_map: dict[str, str] = dict()

        files = os.listdir("data/font")
        for file in files:
            if not file.endswith(".ttf"):
                continue

            path = f"data/font/{file}"
            name = get_font_name(TTFont(path))

            self.path_to_font_map[path] = name
            self.font_to_path_map[name] = path

    def path_to_font(self, path: str):
        return self.path_to_font_map[path]

    def font_to_path(self, font: str):
        return self.font_to_path_map[font]

    def build_css(self):
        result: list[str] = []

        for name, path in self.font_to_path_map.items():
            result.append("@font-face {\n")

            result.append("font-family: '")
            result.append(name)
            result.append("';\n")

            result.append("src: url(/api/fonts/")
            result.append(os.path.basename(path))
            result.append(") format('truetype');\n")

            result.append("}\n")

        return "".join(result)

import os
import re
import tempfile
from contextlib import contextmanager
from typing import Callable, Mapping, Sequence, Any
from threading import Lock

from PIL import Image
from pyhwpx import Hwp

from llm2doc.util import validate_type


REGEX_TABLE_TMPL = re.compile(r"\{\{표:[^\n\r\}]+\}\}")
HWP_COM_LOCK = Lock()


class HwpFile:
    def __init__(self, hwp_obj: Hwp):
        """
        Do not call this directly. Use factory function instead.
        """
        self.hwp = hwp_obj

    @classmethod
    @contextmanager
    def open(cls, path: str):
        """
        Open the specified HWP file.
        Yields a HwpFile instance.
        """
        # CoInitializeEx 인자 뭘로 넣어서 초기화하는지 모르겠으니 일단 락을 넣자
        with HWP_COM_LOCK:
            hwp = Hwp()
            abs_path = os.path.abspath(path)
            if not hwp.open(abs_path):
                hwp.quit()
                raise FileNotFoundError(f"Failed to open HWP file: {abs_path}")

            hwp_file = cls(hwp)
            try:
                yield hwp_file
            finally:
                hwp.quit()

    def save_as(self, path: str):
        """
        Save the document to the specified path.
        """
        self.hwp.save_as(os.path.abspath(path))

    def list_templates(self) -> list[str]:
        """
        Return list of `{{...}}` templates, and fields (누름틀) by name.
        Name does not include `{{` or `}}`.
        """
        # 1. Get Fields (누름틀)
        field_list = self.hwp.get_field_list(number=0).split("\x02")
        fields = [f for f in field_list if f]

        # 2. Get {{...}} templates from text
        self.hwp.init_scan()
        all_text = ""
        while True:
            state, text = self.hwp.get_text()
            if state <= 1:
                break
            all_text += text
        self.hwp.release_scan()

        templates = re.findall(r"\{\{(.*?)\}\}", all_text)

        # Return only normal templates not containing colon
        return [x for x in set(fields + templates) if ":" not in x]

    def list_table_templates(self) -> Mapping[str, int]:
        """
        List table template names and their available column counts.
        """
        self.hwp.init_scan()
        try:
            all_text = ""
            while True:
                state, text = self.hwp.get_text()
                if state <= 1:
                    break
                all_text += text
        finally:
            self.hwp.release_scan()

        templates = REGEX_TABLE_TMPL.findall(all_text)
        results: dict[str, int] = {}

        for tmpl in templates:
            template_str = "{{" + tmpl + "}}"
            self.hwp.MoveDocBegin()
            if self.hwp.find(template_str, direction="AllDoc"):
                if self.hwp.is_cell():
                    # Count columns in row from here
                    addr = self.hwp.get_cell_addr()
                    addr = validate_type(addr, str)
                    row_num = re.sub(r"[A-Z]+", "", addr)

                    pos = self.hwp.get_pos()
                    cols = 1
                    while self.hwp.TableRightCell():
                        new_addr = self.hwp.get_cell_addr()
                        new_addr = validate_type(new_addr, str)
                        if re.sub(r"[A-Z]+", "", new_addr) == row_num:
                            cols += 1
                        else:
                            break
                    results[tmpl] = cols
                    self.hwp.set_pos(*pos)
                else:
                    results[tmpl] = 1
        return results

    def replace_templates(self, mapping: Mapping[str, str | Callable[["HwpFile"], Any]]):
        """
        Write template into the file.
        `mapping` key is name returned by `list_templates`.
        `mapping` value is either text to be written, or custom funciton for rich text.
        """
        for name, value in mapping.items():
            # Try finding as field first
            if self.hwp.field_exist(name):
                field_list = self.hwp.get_field_list(number=1).split("\x02")
                field_list = validate_type(field_list, list[str])
                indices = []
                for f in field_list:
                    # Match name{{idx}}
                    match = re.match(rf"^{re.escape(name)}\{{{{(\d+)\}}}}$", f)
                    if match:
                        indices.append(int(match.group(1)))
                    elif f == name:
                        indices.append(0)

                indices.sort()

                if not indices and self.hwp.field_exist(name):
                    indices = [0]

                if isinstance(value, str):
                    # put_field_text(name, value) replaces all of them by default
                    self.hwp.put_field_text(name, value)
                elif callable(value):
                    # For callable, we must visit each one.
                    for idx in indices:
                        if self.hwp.move_to_field(name, idx=idx):
                            value(self)
            else:
                # Try finding as {{name}}
                template_str = "{{" + name + "}}"
                self.hwp.MoveDocBegin()
                # Find all occurrences sequentially
                count = 0
                while self.hwp.find(template_str, direction="Forward"):
                    if isinstance(value, str):
                        self.act_write_text(value)
                    elif callable(value):
                        value(self)
                    count += 1
                    if count > 1000:
                        raise RuntimeError("Failed to replace template. Is template recursive?")

    def replace_table_templates(self, mapping: Mapping[str, Sequence[str]]):
        """
        Replace table templates with sequences of strings.
        """
        for name, values in mapping.items():
            template_str = "{{" + name + "}}"
            self.hwp.MoveDocBegin()
            count = 0
            while self.hwp.find(template_str, direction="Forward"):
                if not values:
                    break

                # Replace first cell
                self.act_write_text(values[0])

                # Fill subsequent cells
                for val in values[1:]:
                    if self.hwp.TableRightCell():
                        self.hwp.TableCellBlock()
                        self.hwp.Delete()
                        self.hwp.insert_text(val)
                    else:
                        break

                count += 1
                if count > 1000:
                    raise RuntimeError("Failed to replace table template. Is template recursive?")

    def act_write_text(self, text: str, bold: bool = False, underline: bool = False):
        """
        Write text at current caret.
        """
        if bold or underline:
            self.hwp.set_font(Bold=bold, UnderlineType=1 if underline else 0)

        self.hwp.insert_text(text)

        if bold or underline:
            self.hwp.set_font(Bold=False, UnderlineType=0)

    def act_write_table(self, data: Sequence[Sequence[str]]):
        """
        Write table at current caret.
        """
        if not data:
            return

        rows = len(data)
        cols = len(data[0])

        # create_table moves caret to the first cell
        self.hwp.create_table(rows=rows, cols=cols, header=False)

        for r_idx, row in enumerate(data):
            for c_idx, cell_text in enumerate(row):
                self.hwp.insert_text(str(cell_text))
                if not (r_idx == rows - 1 and c_idx == cols - 1):
                    self.hwp.TableRightCell()

    def act_write_image(self, image: Image.Image, treat_as_char: bool=False, fit: bool=False):
        """
        Insert image at current caret
        """
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            image.save(f.name)
            self.hwp.insert_picture(f.name, sizeoption=3 if fit else 0, treat_as_char=treat_as_char)

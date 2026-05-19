import os
import re
import tempfile
from contextlib import contextmanager
from typing import Callable, Mapping, Sequence, Any, NewType

from PIL import Image
from pyhwpx import Hwp

from llm2doc.util import validate_type


REGEX_TABLE_TMPL = re.compile(r"\{\{표:.*?\}\}")
REGEX_RICH_TAG = re.compile(r"(</?[buBU](?:\s+[^>]*)?>)")

HCharShape = NewType("HCharShape", object)


class HwpFile:
    def __init__(self, hwp_obj: Hwp, debug: bool):
        """
        Do not call this directly. Use factory function instead.
        """
        self._hwp = hwp_obj
        self._debug = debug

    @classmethod
    @contextmanager
    def open(cls, path: str, debug: bool = False):
        """
        Open the specified HWP file.
        Yields a HwpFile instance.
        """
        hwp = Hwp(visible=debug)
        abs_path = os.path.abspath(path)
        if not hwp.open(abs_path):
            hwp.quit()
            raise FileNotFoundError(f"Failed to open HWP file: {abs_path}")

        hwp_file = cls(hwp, debug)
        try:
            yield hwp_file
        finally:
            hwp.quit()

    def save_as(self, path: str):
        """
        Save the document to the specified path.
        """
        self._hwp.save_as(os.path.abspath(path))

    def _list_all_templates(self) -> list[str]:
        # 1. Get Fields (누름틀)
        field_list = self._hwp.get_field_list(number=0).split("\x02")
        fields = [f for f in field_list if f]

        # 2. Get {{...}} templates from text
        self._hwp.init_scan()
        all_text = ""
        while True:
            state, text = self._hwp.get_text()
            if state <= 1:
                break
            all_text += text
        self._hwp.release_scan()

        templates = re.findall(r"\{\{(.*?)\}\}", all_text)

        return fields + templates

    def list_templates(self) -> list[str]:
        """
        Return list of `{{...}}` templates, and fields (누름틀) by name.
        Name does not include `{{` or `}}`.
        """

        # Return only normal templates not containing colon
        return list(set([x for x in self._list_all_templates() if ":" not in x]))

    def list_table_templates(self) -> Mapping[str, int]:
        """
        List table template names and their available column counts.
        """

        templates = list(set([x for x in self._list_all_templates() if x.startswith("표:")]))
        results: dict[str, int] = {}

        for tmpl in templates:
            template_str = "{{" + tmpl + "}}"
            self._hwp.MoveDocBegin()
            if self._hwp.find(template_str, direction="AllDoc"):
                if self._hwp.is_cell():
                    # Count columns in row from here
                    addr = self._hwp.get_cell_addr()
                    addr = validate_type(addr, str)
                    row_num = re.sub(r"[A-Z]+", "", addr)

                    pos = self._hwp.get_pos()
                    cols = 1
                    while self._hwp.TableRightCell():
                        new_addr = self._hwp.get_cell_addr()
                        new_addr = validate_type(new_addr, str)
                        if re.sub(r"[A-Z]+", "", new_addr) == row_num:
                            cols += 1
                        else:
                            break
                    results[tmpl] = cols
                    self._hwp.set_pos(*pos)
                else:
                    results[tmpl] = 1
        return results

    def replace_templates(self, mapping: Mapping[str, str | Callable[["HwpFile"], Any]]):
        """
        Write template into the file.
        `mapping` key is name returned by `list_templates`.
        `mapping` value is either text to be written, or custom funciton for rich text.
        """

        existing_templates = set(self.list_templates())
        new_templates = set(mapping.keys())
        if existing_templates != new_templates:
            missing = existing_templates - new_templates
            surplus = new_templates - existing_templates
            raise ValueError(f"Template mismatch. Missing: {missing}, Surplus: {surplus}")

        for name, value in mapping.items():
            # Try finding as field first
            if self._hwp.field_exist(name):
                field_list = self._hwp.get_field_list(number=1).split("\x02")
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

                if not indices and self._hwp.field_exist(name):
                    indices = [0]

                if isinstance(value, str):
                    # put_field_text(name, value) replaces all of them by default
                    self._hwp.put_field_text(name, value)
                elif callable(value):
                    # For callable, we must visit each one.
                    for idx in indices:
                        if self._hwp.move_to_field(name, idx=idx):
                            value(self)
            else:
                # Try finding as {{name}}
                template_str = "{{" + name + "}}"
                self._hwp.MoveDocBegin()
                # Find all occurrences sequentially
                count = 0
                while self._hwp.find(template_str, direction="AllDoc"):
                    self._hwp.Delete()
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

        existing_templates = set(self.list_table_templates())
        new_templates = set(mapping.keys())
        if existing_templates != new_templates:
            missing = existing_templates - new_templates
            surplus = new_templates - existing_templates
            raise ValueError(f"Template mismatch. Missing: {missing}, Surplus: {surplus}")

        for name, values in mapping.items():
            template_str = "{{" + name + "}}"
            self._hwp.MoveDocBegin()
            count = 0
            while self._hwp.find(template_str, direction="AllDoc"):
                if not values:
                    break

                assert self._hwp.is_cell()

                # Replace first cell
                self._hwp.Delete()
                self._hwp.insert_text(values[0])

                # Fill subsequent cells
                for val in values[1:]:
                    if self._hwp.TableRightCell():
                        self._hwp.TableCellBlock()
                        self._hwp.Delete()
                        self._hwp.insert_text(val)
                    else:
                        break

                count += 1
                if count > 1000:
                    raise RuntimeError("Failed to replace table template. Is template recursive?")

    def get_charshape(self) -> Any:
        """
        Get character shape at current caret position.
        """
        return self._hwp.get_charshape()

    def set_charshape(self, shape: HCharShape):
        """
        Set character shape at current caret position.
        """
        self._hwp.set_charshape(shape)

    def move_to_template(self, name: str) -> bool:
        """
        Move caret to the first occurrence of the template.
        Returns True if found, False otherwise.
        """
        # Try finding as field first
        if self._hwp.field_exist(name):
            if self._hwp.move_to_field(name):
                return True

        # Try finding as {{name}}
        template_str = "{{" + name + "}}"
        self._hwp.MoveDocBegin()
        return self._hwp.find(template_str, direction="AllDoc")

    def get_template_charshape(self, name: str) -> HCharShape:
        """
        Find a template and return its character shape.
        Caret position is restored after sampling.
        """
        pos = self._hwp.get_pos()
        try:
            if self.move_to_template(name):
                return self.get_charshape()
            raise ValueError(f"Template '{name}' not found")
        finally:
            self._hwp.set_pos(*pos)

    def act_write_text(self, text: str, shape: HCharShape | None = None):
        """
        Write text at current caret.
        """

        old_shape = self.get_charshape()
        try:
            if shape is not None:
                self.set_charshape(shape)
            self._hwp.insert_text(text)
        finally:
            if shape is not None:
                self.set_charshape(old_shape)

    def act_write_text_rich(self, rich_text: str, shape: HCharShape | None = None):
        """
        Write rich text at current caret.
        Supports `<b>` and `<u>` HTML tags.
        """
        parts = REGEX_RICH_TAG.split(rich_text)
        bold_stack = 0
        underline_stack = 0

        old_shape = self.get_charshape()
        if shape is not None:
            self.set_charshape(shape)
        else:
            shape = old_shape

        assert shape is not None

        try:
            for part in parts:
                if not part:
                    continue
                low = part.lower()
                if low.startswith("<b"):
                    bold_stack += 1
                elif low == "</b>":
                    bold_stack = max(0, bold_stack - 1)
                    if bold_stack == 0:
                        self._hwp.set_font(Bold=False)
                elif low.startswith("<u"):
                    underline_stack += 1
                elif low == "</u>":
                    underline_stack = max(0, underline_stack - 1)
                    if underline_stack == 0:
                        self._hwp.set_font(UnderlineType=0)
                else:
                    self.set_charshape(shape)
                    if bold_stack > 0:
                        self._hwp.set_font(Bold=True)
                    if underline_stack > 0:
                        self._hwp.set_font(UnderlineType=1)

                    self._hwp.insert_text(part)
        finally:
            self.set_charshape(old_shape)

    def act_write_table(self, data: Sequence[Sequence[str]]):
        """
        Write table at current caret.
        """
        if not data:
            return

        rows = len(data)
        cols = len(data[0])

        # create_table moves caret to the first cell
        self._hwp.create_table(rows=rows, cols=cols, header=False)

        for r_idx, row in enumerate(data):
            for c_idx, cell_text in enumerate(row):
                self._hwp.insert_text(str(cell_text))
                if not (r_idx == rows - 1 and c_idx == cols - 1):
                    self._hwp.TableRightCell()

    def act_write_image(self, image: Image.Image, treat_as_char: bool=False, fit: bool=False):
        """
        Insert image at current caret
        """
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            image.save(f.name)
            self._hwp.insert_picture(f.name, sizeoption=3 if fit else 0, treat_as_char=treat_as_char)

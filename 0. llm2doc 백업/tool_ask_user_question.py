import json
from typing import Sequence
from openai.types.responses.response_input_param import FunctionCallOutput


class ToolAskUserQuestion:
    def __init__(self):
        super().__init__()

        self.description = {
            "type": "function",
            "name": "ask_user_question",
            "description": "Ask the user a question with suggested choices. User may also enter custom answers.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user. Must be Korean.",
                    },
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Suggested answer options to present to the user. Must be Korean.",
                        "minItems": 1,
                    },
                },
                "required": ["question", "choices"],
                "additionalProperties": False,
            },
        }

    def invoke(self, param: str, call_id: str) -> FunctionCallOutput:
        param_parsed = json.loads(param)
        question: str = param_parsed["question"]
        choices: Sequence[str] = param_parsed["choices"]

        answer = self.ask(question, choices).strip()

        if len(answer) == 0:
            return {
                "type": "function_call_output",
                "output": "The user refused to provide an answer.",
                "call_id": call_id,
            }

        return {
            "type": "function_call_output",
            "output": answer,
            "call_id": call_id,
        }

    def ask(self, question: str, choices: Sequence[str]):
        print()
        print(question)
        for i, x in enumerate(choices):
            print(f"[{i + 1}] {x}")

        print(f"[{len(choices) + 1}] 답변 직접 입력")

        while True:
            try:
                choice = int(input("답변 번호: "), base=10)
            except ValueError:
                continue

            if choice == len(choices) + 1:
                return input("답변: ")

            try:
                return choices[choice - 1]
            except IndexError:
                continue

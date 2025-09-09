import os
import json
import re
from typing import Dict, Any, List, Tuple

from PyPDF2 import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from dotenv import load_dotenv

load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")

# ---------- PDF Processing ----------
def extract_text_from_pdf(file) -> str:
    """Read text from a PDF (Streamlit's UploadedFile or path-like)."""
    reader = PdfReader(file)
    text = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text.append(page_text)
    return "\n".join(text)

def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 240) -> List[str]:
    """Split text for prompt friendliness."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=overlap
    )
    return splitter.split_text(text)

# ---------- Prompt & Chain ----------
def _build_quiz_prompt(questions_per_level: int) -> PromptTemplate:
    return PromptTemplate(
        input_variables=["content", "n_per_level"],
        template="""
You are an AI quiz generator. Based on the study material, create a STRICT JSON object with exactly:
- {n_per_level} Basic questions (easy)
- {n_per_level} Intermediate questions
- {n_per_level} Hard questions

Each question MUST be an object with:
- "question": string
- "options": {{ "A": string, "B": string, "C": string, "D": string }}
- "correct": one of "A","B","C","D"
- "explanation": string (1–2 lines)

Important rules:
- Output JSON ONLY, no prose before or after.
- Do NOT include backticks.
- All values must be plain strings (no nested JSON inside strings).
- The JSON top-level keys must be exactly: "basic", "intermediate", "hard".

Study material:
{content}

Output JSON ONLY:
{{
  "basic": [ {{ "question": "...", "options": {{ "A": "...", "B": "...", "C": "...", "D": "..." }}, "correct": "A", "explanation": "..." }} ],
  "intermediate": [],
  "hard": []
}}
"""
    )

def _make_chain(model_name: str = "gpt-4o-mini", temperature: float = 0.7) -> LLMChain:
    llm = ChatOpenAI(model=model_name, temperature=temperature)
    # Prompt will be provided at call time to allow different n_per_level
    return LLMChain(llm=llm, prompt=_build_quiz_prompt(5))

# ---------- JSON Helpers ----------
def _extract_json_block(text: str) -> str:
    """
    Find the first {...} JSON block from a model response.
    """
    match = re.search(r"\{[\s\S]*\}\s*$", text.strip())
    if not match:
        # Fallback: greedy from first "{" to last "}"
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in model output.")
        return text[start : end + 1]
    return match.group(0)

def _validate_quiz_schema(data: Dict[str, Any], n_per_level: int) -> None:
    """
    Lightweight schema validation to avoid runtime surprises.
    Raises ValueError on problems.
    """
    for level in ["basic", "intermediate", "hard"]:
        if level not in data or not isinstance(data[level], list):
            raise ValueError(f'Missing or invalid "{level}" list in quiz JSON.')
        if len(data[level]) != n_per_level:
            # Not fatal, but we keep strict to your setting
            raise ValueError(
                f'"{level}" must have exactly {n_per_level} questions; got {len(data[level])}.'
            )
        for idx, q in enumerate(data[level]):
            if not isinstance(q, dict):
                raise ValueError(f"{level}[{idx}] is not an object.")
            for key in ["question", "options", "correct", "explanation"]:
                if key not in q:
                    raise ValueError(f'Missing key "{key}" in {level}[{idx}].')
            if not isinstance(q["options"], dict):
                raise ValueError(f'{level}[{idx}].options must be an object.')
            for k in ["A", "B", "C", "D"]:
                if k not in q["options"]:
                    raise ValueError(f'Missing option "{k}" in {level}[{idx}].options.')
            if q["correct"] not in ["A", "B", "C", "D"]:
                raise ValueError(f'Invalid correct value in {level}[{idx}].')

# ---------- Public API ----------
def generate_quiz_from_text(
    content: str,
    questions_per_level: int = 5,
    model_name: str = "gpt-4o-mini",
    temperature: float = 0.7,
) -> Dict[str, Any]:
    """
    Build quiz JSON (as dict) from provided content text.
    """
    chain = LLMChain(llm=ChatOpenAI(model=model_name, temperature=temperature),
                     prompt=_build_quiz_prompt(questions_per_level))
    raw = chain.run(content=content, n_per_level=str(questions_per_level))

    # Try parse
    json_str = _extract_json_block(raw)
    data = json.loads(json_str)

    # Validate (raises if issues)
    _validate_quiz_schema(data, questions_per_level)
    return data

def evaluate_answers(user_answers: Dict[str, str], quiz_data: Dict[str, Any]) -> Tuple[int, List[Dict[str, str]]]:
    """
    user_answers keys like: "basic_0", "intermediate_3", etc. Values are "A"/"B"/"C"/"D".
    """
    score = 0
    feedback = []

    for level in ["basic", "intermediate", "hard"]:
        for i, question in enumerate(quiz_data[level]):
            correct = question["correct"].strip().upper()
            user_answer = user_answers.get(f"{level}_{i}", "").strip().upper()

            if user_answer == correct:
                score += 1
                result = "Correct"
            else:
                result = f"Wrong (Correct: {correct})"

            feedback.append(
                {
                    "question": question["question"],
                    "result": result,
                    "explanation": question["explanation"],
                }
            )
    return score, feedback

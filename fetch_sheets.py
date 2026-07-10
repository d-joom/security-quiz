"""
Google Sheets에서 문제 데이터를 가져와 questions_bank.json에 병합하는 스크립트
시트 구조: 열1=답, 열2=문제
사용법: python fetch_sheets.py
"""

import json
import re
import urllib.request
import urllib.parse

SPREADSHEET_ID = "1Af8diBgdAGmSDN4nc2uHrlEPjx2j5W5hcOh8o7iEqvY"
SOURCE_LABEL = "요약시트"

SUBJECT_MAP = {
    1: "시스템보안",
    2: "네트워크보안",
    3: "어플리케이션보안",
    4: "정보보안일반",
    5: "보안관리및법규",
}

# (시트명, 과목번호, 유형, A열이_답인지) — 없는 시트는 sig 중복으로 자동 스킵
# 단답형: A열=답, B열=문제 / 서술형: A열=문제, B열=답
SHEET_NAMES = [
    ("단답형(1)", 1, "단답형", True),
    ("서술형(1)", 1, "서술형", False),
    ("단답형(2)", 2, "단답형", True),
    ("서술형(2)", 2, "서술형", False),
    ("단답형(3)", 3, "단답형", True),
    ("서술형(3)", 3, "서술형", False),
    ("단답형(4)", 4, "단답형", True),
    ("서술형(4)", 4, "서술형", False),
    ("단답형(5)", 5, "단답형", True),
    ("서술형(5)", 5, "서술형", False),
]

OUTPUT_FILE = "questions_bank.json"

HEADER_LABELS = {"답", "정답", "answer", "Answer", "문제", "question", "Question"}


def fetch_gviz(sheet_name: str) -> dict:
    encoded = urllib.parse.quote(sheet_name, safe="", encoding="utf-8")
    url = (
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
        f"/gviz/tq?tqx=out:json&sheet={encoded}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
    m = re.search(r"setResponse\((\{.*\})\)", raw, re.DOTALL)
    if not m:
        raise ValueError("gviz 응답 파싱 실패")
    return json.loads(m.group(1))


def get_sig(data: dict) -> str:
    return data.get("sig", "")


def parse_gviz(data: dict, subject_num: int, q_type: str, a_col_is_answer: bool) -> list[dict]:
    subject = SUBJECT_MAP[subject_num]
    table = data.get("table", {})
    rows = table.get("rows", [])

    items: list[tuple[str, str]] = []

    # cols[].label(1행)은 신뢰할 수 없어 무시, rows만 사용
    for row in rows:
        c = row.get("c") or []
        if len(c) < 2:
            continue
        col_a = str(c[0].get("v") or "").strip() if c[0] else ""
        col_b = str(c[1].get("v") or "").strip() if c[1] else ""
        # 헤더행 스킵 (예: "문제"/"답" 레이블)
        if col_a in HEADER_LABELS or col_b in HEADER_LABELS:
            continue
        if not col_a or not col_b:
            continue
        if a_col_is_answer:
            ans, q_text = col_a, col_b   # 단답형: A=답, B=문제
        else:
            ans, q_text = col_b, col_a   # 서술형: A=문제, B=답
        items.append((ans, q_text))

    questions = []
    for i, (answer, question) in enumerate(items, start=1):
        q_id = f"sheet_{q_type[0]}_{subject_num}_{i:03d}"
        keywords = [kw.strip() for kw in re.split(r"\n|\(\d+\)\s*", answer) if kw.strip()]
        keywords = [k for k in keywords if k and len(k) < 60][:5]
        questions.append({
            "id": q_id,
            "source": SOURCE_LABEL,
            "exam": subject,
            "subject_num": subject_num,
            "number": i,
            "type": q_type,
            "points": 5 if q_type == "서술형" else 3,
            "question": question,
            "answer": answer,
            "keywords": keywords,
            "commentary": "",
            "difficulty": "",
            "sub_questions": None,
        })
    return questions


def load_existing() -> list[dict]:
    try:
        with open(OUTPUT_FILE, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except FileNotFoundError:
        return []


def save(data: list[dict]):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open("data.js", "w", encoding="utf-8") as f:
        f.write("window.QUESTIONS_DATA = ")
        json.dump(data, f, ensure_ascii=False)
        f.write(";")


def main():
    existing = load_existing()
    base = [q for q in existing if q.get("source") != SOURCE_LABEL and not q.get("id", "").startswith("sheet_")]
    base_questions = {q["question"].strip() for q in base}

    seen_sigs: set[str] = set()
    new_questions: list[dict] = []

    for sheet_name, subject_num, q_type, a_col_is_answer in SHEET_NAMES:
        print(f"  [{sheet_name}] 가져오는 중...", end=" ", flush=True)
        try:
            data = fetch_gviz(sheet_name)
            sig = get_sig(data)

            if sig in seen_sigs:
                print("스킵 (미작성 시트)")
                continue
            seen_sigs.add(sig)

            parsed = parse_gviz(data, subject_num, q_type, a_col_is_answer)

            added = []
            seen_in_batch = {q["question"].strip() for q in new_questions}
            for q in parsed:
                key = q["question"].strip()
                if key in base_questions or key in seen_in_batch:
                    continue
                added.append(q)

            new_questions.extend(added)
            print(f"{len(parsed)}개 파싱, {len(added)}개 추가")

        except Exception as e:
            print(f"실패 ({e})")

    merged = base + new_questions
    save(merged)
    print(f"\n완료: 요약시트 {len(new_questions)}개 -> 총 {len(merged)}개")


if __name__ == "__main__":
    main()

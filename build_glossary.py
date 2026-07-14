# -*- coding: utf-8 -*-
"""
'정보보안기사 요약 정리.pdf'를 term:definition 구조로 재구성.
(카드형 문제은행이 아니라, PDF의 "타이틀 / 단어 ○ 개념" 레이아웃을 그대로
 웹에서 예쁘게 보여주기 위한 구조화 데이터를 만든다.)
"""
import json
import re
import pdfplumber

PDF_PATH = r'C:\development\security-quiz\정보보안기사 요약 정리.pdf'

CHAPTER_MARK = re.compile(r'^>\s*')
TAG_RE = re.compile(r'\s*\[([^\[\]]{1,12})\]\s*$')
FOOTER_RE = re.compile(r'^정보보안기사\s*페이지\s*\d+$')


def split_won(line):
    """'term ○ defn' -> (term, defn) / '○defn' -> ('', defn) / no ○ -> None"""
    idx = line.find('○')
    if idx == -1:
        return None
    left = line[:idx].strip()
    right = line[idx + 1:].strip()
    return left, right


BRACKET_ONLY_RE = re.compile(r'^\[([^\[\]]{1,12})\]$')
GLOSS_ONLY_RE = re.compile(r'^\([^()]{1,20}\)$')
GLOSS_DASH_RE = re.compile(r'^\(([^()]{1,20})\)\s*(-.*)$')
DASH_SUBITEM_RE = re.compile(r'^-\s*\S')
PURE_BRACKET_TERM_RE = re.compile(r'^\[[^\[\]]+\]$')


def paren_delta(s):
    # 소괄호와 대괄호 모두 "아직 안 닫힘"의 신호로 취급 (예: '[정성적 위험 분' 처럼
    # 대괄호로 줄바꿈되는 용어도 소괄호와 같은 방식으로 이어붙이기 위함)
    return (s.count('(') - s.count(')')) + (s.count('[') - s.count(']'))


def parse_term_pages(pages_text):
    """pages_text: list of (page_no, text) for term-table style pages.
    Returns list of chapters: {title, blocks: [...]} where each block is
    {type:'entry', term, mnemonic, defs:[...]} or {type:'note', text} (원문 순서 그대로).

    표는 [용어(여러 줄로 줄바꿈될 수 있음)] | [○ bullet 여러 개] 두 칸으로 되어 있다.
    용어 칸이 여러 줄로 줄바꿈되는 경우는 대부분 괄호가 아직 닫히지 않은 경우이므로,
    누적된 용어 텍스트의 괄호 균형(open '(' 개수 - close ')' 개수)으로 "아직 용어가
    이어지는 중"인지 판단한다. 균형이 0이 되면 그 용어는 완성된 것으로 보고,
    이후 새로운 좌측 텍스트가 나오면 새 항목(row)으로 취급한다.
    """
    chapters = []
    cur_chapter = {'title': '', 'blocks': []}

    cur_entry = None       # {'term_parts': [...], 'defs': [...]}
    balance = 0            # 현재 엔트리 용어의 괄호 균형 (>0 이면 아직 용어가 이어지는 중)
    last_entry_block = None  # 방금 flush된 엔트리 블록 (뒤따르는 '[태그]' 단독 줄을 붙이기 위함)
    pending_notes = []      # ○ 없는 연속 줄을 하나의 문단으로 묶기 위한 버퍼
    last_line = None       # 페이지 경계에서 중복 행 감지용

    def joined_term(entry):
        return ' '.join(p for p in entry['term_parts'] if p).strip()

    def flush_notes():
        nonlocal pending_notes
        if pending_notes:
            cur_chapter['blocks'].append({'type': 'note', 'text': '\n'.join(pending_notes)})
            pending_notes = []

    def flush_entry():
        nonlocal cur_entry, last_entry_block
        if cur_entry is None:
            return
        flush_notes()
        term = joined_term(cur_entry)
        # 줄바꿈으로 나뉜 용어를 이어붙이며 생긴, 닫는 괄호 앞의 어색한 공백 제거
        term = re.sub(r'\s+([)\]])', r'\1', term)
        defs = [d for d in cur_entry['defs'] if d]
        if term or defs:
            block = {'type': 'entry', 'term': term or '(계속)', 'mnemonic': cur_entry.get('mnemonic'), 'defs': defs}
            cur_chapter['blocks'].append(block)
            last_entry_block = block
        cur_entry = None

    for page_no, text in pages_text:
        if not text:
            continue
        page_lines = [l.strip() for l in text.split('\n') if l.strip() and not FOOTER_RE.match(l.strip())]

        # PDF가 페이지 넘김 시 표의 마지막 행을 다음 페이지 상단에 그대로 반복해 찍는 경우가 있어
        # 이전 페이지의 마지막 줄과 완전히 동일한 첫 줄은 건너뛴다.
        if page_lines and last_line is not None and page_lines[0] == last_line:
            page_lines = page_lines[1:]

        for line in page_lines:
            last_line = line

            if CHAPTER_MARK.match(line):
                # 새 챕터 시작 (제목 줄 자체만 사용, 다음 줄들은 일반 본문으로 처리)
                flush_entry()
                flush_notes()
                last_entry_block = None
                if cur_chapter['blocks'] or cur_chapter['title']:
                    chapters.append(cur_chapter)
                cur_chapter = {'title': CHAPTER_MARK.sub('', line).strip(), 'blocks': []}
                continue

            parts = split_won(line)
            if parts is None:
                if cur_entry is not None and balance > 0:
                    # 용어가 아직 괄호를 닫지 못한 채 줄바꿈된 경우 (정의 칸은 비어있는 행)
                    cur_entry['term_parts'].append(line)
                    balance += paren_delta(line)
                    continue

                gm = GLOSS_DASH_RE.match(line)
                if gm and cur_entry is not None and balance <= 0:
                    # 예: '위협 ○...' 다음 줄이 '(Threat) -의도적: ...'
                    # -> 짧은 영문 표기는 용어에 이어붙이고, '-'로 시작하는 하위 항목은 정의에 추가
                    cur_entry['term_parts'].append('(' + gm.group(1) + ')')
                    cur_entry['defs'].append(gm.group(2).strip())
                    continue

                if DASH_SUBITEM_RE.match(line) and cur_entry is not None:
                    # '-'로 시작하는 줄은 새 항목이 아니라 직전 ○ 항목의 하위(들여쓰기) 항목
                    cur_entry['defs'].append(line)
                    continue

                delta = paren_delta(line)
                if delta > 0:
                    # 새 항목의 용어가 첫 줄부터 괄호를 닫지 못한 채 시작 (정의는 다음 줄의 ○에서 옴)
                    flush_entry()
                    cur_entry = {'term_parts': [line], 'defs': []}
                    balance = delta
                    continue
                # 이어지는 용어 wrap이 아니라면 먼저 지금까지의 엔트리를 확정
                flush_entry()
                bm = BRACKET_ONLY_RE.match(line)
                if bm and last_entry_block is not None and not pending_notes:
                    # 예: '자산중요도평가 ○...' 다음 줄에 홀로 '[자산목록]' -> 방금 항목의 태그로 붙임
                    last_entry_block['mnemonic'] = bm.group(1)
                    continue
                # 그 외 ○ 없는 줄: 소제목(그룹 헤더) 또는 참고 메모 -> 문단으로 누적
                # (PDF가 같은 제목 줄을 연달아 중복 인쇄하는 경우가 있어 바로 직전과 동일하면 무시)
                if not pending_notes or pending_notes[-1] != line:
                    pending_notes.append(line)
                continue

            left, right = parts
            if left:
                bm = BRACKET_ONLY_RE.match(left)
                gm = GLOSS_ONLY_RE.match(left)
                if bm and cur_entry is not None and balance <= 0:
                    # 예: '자산중요도평가 ○...' 다음 줄이 '[자산분석] ○...' -> 태그+추가 정의로 흡수
                    cur_entry['defs'].append(right)
                    cur_entry['mnemonic'] = bm.group(1)
                elif gm and cur_entry is not None and balance <= 0:
                    # 예: '취약점 ○...' 다음 줄이 '(Vulnerability) ○...' -> 용어에 영문 표기 이어붙이고 정의 추가
                    cur_entry['term_parts'].append(left)
                    cur_entry['defs'].append(right)
                elif (cur_entry is not None and balance <= 0 and len(left) <= 20
                        and paren_delta(left) < 0 and left.endswith(')') and '(' not in left):
                    # PDF에서 여는 괄호 글자가 유실된 경우 (예: '위험 ○...' 다음 줄 'Risk) ○...') -> 이어붙이며 여는 괄호 복원
                    cur_entry['term_parts'].append('(' + left)
                    cur_entry['defs'].append(right)
                elif cur_entry is not None and balance > 0:
                    # 아직 괄호가 안 닫힌 용어가 이어지는 중 -> 이어붙임
                    cur_entry['term_parts'].append(left)
                    cur_entry['defs'].append(right)
                    balance += paren_delta(left)
                elif (cur_entry is not None and balance <= 0
                        and PURE_BRACKET_TERM_RE.match(joined_term(cur_entry))):
                    # 예: '[정성적 위험 분석] ○...' 다음 줄이 '델파이법 ○...'
                    # -> 직전 용어가 '[카테고리]' 라벨만으로 끝났다면 세부 용어를 이어붙임
                    cur_entry['term_parts'].append(left)
                    cur_entry['defs'].append(right)
                else:
                    flush_entry()
                    cur_entry = {'term_parts': [left], 'defs': [right]}
                    balance = paren_delta(left)
            else:
                # 왼쪽 비어있음: 순수 연속 bullet (용어 칸은 이미 끝난 상태)
                if cur_entry is None:
                    cur_entry = {'term_parts': [], 'defs': [right]}
                else:
                    cur_entry['defs'].append(right)

        # 페이지가 끝나도 용어 괄호가 안 닫혔다면(드묾) 다음 페이지에서 계속 이어붙일 수 있게 유지
        # (balance, cur_entry는 페이지 경계를 넘어 그대로 유지됨)

    flush_entry()
    flush_notes()
    if cur_chapter['blocks'] or cur_chapter['title']:
        chapters.append(cur_chapter)

    for ch in chapters:
        for block in ch['blocks']:
            if block['type'] != 'entry':
                continue
            if block['mnemonic'] is None and block['defs']:
                m = TAG_RE.search(block['defs'][-1])
                if m:
                    block['mnemonic'] = m.group(1)
                    block['defs'][-1] = TAG_RE.sub('', block['defs'][-1]).strip()
            block['defs'] = [d for d in block['defs'] if d]

    apply_manual_fixes(chapters)
    classify_mnemonics(chapters)

    return chapters


# 나열된 항목 개수 매칭으로는 잡히지 않는(문장 속에 녹아든 형태) 두문자어들.
# 검수 중 발견되는 대로 추가한다.
MANUAL_ACRONYM_OVERRIDE = {'돈키', '위보', '상점비환', '예피발복'}


def classify_mnemonic(mnemonic, defs):
    """대괄호(또는 태그) 표기가 '자산목록'처럼 뜻이 있는 부제(label)인지,
    '자위취'처럼 나열된 항목들의 앞 글자만 딴 암기용 두문자어(acronym)인지 구분한다.
    -> 정의문 중 콤마(,)/화살표(>)/슬래시(/)로 나열된 항목 개수, 또는 정의(bullet) 개수 자체가
       표기 글자 수와 정확히 같으면 두문자어로 판단.
    """
    if not mnemonic or len(mnemonic) < 2:
        return 'label'
    if mnemonic in MANUAL_ACRONYM_OVERRIDE:
        return 'acronym'
    n = len(mnemonic)
    if len(defs) == n:
        return 'acronym'
    for d in defs:
        for sep in (',', '>', '/'):
            parts = [p.strip() for p in d.split(sep) if p.strip()]
            if len(parts) == n:
                return 'acronym'
    return 'label'


def classify_mnemonics(chapters):
    for ch in chapters:
        for block in ch['blocks']:
            if block['type'] == 'entry' and block.get('mnemonic'):
                block['mnemonic_type'] = classify_mnemonic(block['mnemonic'], block['defs'])


# ─────────────────────────────────────────────
# 수동 보정
# ─────────────────────────────────────────────
# 용어 칸이 괄호 없이(따라서 자동 판별 불가) 2줄 이상으로 줄바꿈되는 경우는
# 이어지는 다음 항목(entry)의 새 용어인지, 직전 용어의 연속인지 텍스트만으로는
# 구분이 불가능하다. 검수 중 발견되는 대로 여기에 규칙을 추가한다.
# (questions_bank.json을 fix_*.py로 수동 보정해온 것과 같은 방식)

# 챕터 안에서 완전히 삭제할 용어 (원문 자체가 중복/혼동을 주는 경우)
MANUAL_DELETE_TERMS = {
    ('정보보안관리 및 법규', '정보보호 3대 요소'),
}

# 챕터 안에서 완전히 삭제할 note (예: 도둑 비유 같은 별도 설명 문단, 중복/의미없는 제목 줄)
MANUAL_DELETE_NOTES = {
    ('정보보안관리 및 법규', '위험 분석 방법론\n분류'),
}
MANUAL_DELETE_NOTE_PREFIXES = {
    # note 텍스트가 이 접두어로 시작하면 통째로 삭제 (여러 줄로 나뉜 긴 비유/일화 설명)
    ('정보보안관리 및 법규', '위협/취약점/위험 나보석씨의'),
}

# 바로 뒤에 오는 note를 직전 entry의 용어에 이어붙여야 하는 경우.
# 같은 term이 챕터 내에 여러 번 등장할 수 있어, defs 첫 줄 접두어로 특정 항목을 지목한다.
# (챕터, 직전 entry의 term, 직전 entry defs[0]의 접두어) -> 병합 후 새 term
MANUAL_MERGE_TRAILING_NOTE = {
    ('정보보안관리 및 법규', '정보보호의', '기밀성, 무결성, 가용성, 인증, 부인방지'): '정보보호의 5대 목표',
    ('정보보안관리 및 법규', '위험 평가', '자산, 위협, 취약점'): '위험 평가 기본 요소',
    ('정보보안관리 및 법규', '비정형화된 접근', '분석을 수행하는 개개인의 지식과 전문성'): '비정형화된 접근법',
    ('정보보안관리 및 법규', '개인 정보 시스템 권', '권한 부여, 변경, 말소'): '개인 정보 시스템 권한 부여 기록 유지',
    ('정보보안관리 및 법규', '개인 정보 처리', '접속한 기록은'): '개인 정보 처리 시스템 접속 기록',
}

# 다음 entry가 사실은 직전 entry 용어의 연속인 경우 (둘 다 자기 ○ 항목을 갖고 있어 각각
# entry로 만들어졌지만, 실제로는 하나의 용어+정의). defs는 순서대로 이어붙인다.
# (챕터, 직전 entry의 term) -> 병합 후 새 term
MANUAL_MERGE_ENTRY_PAIR = {
    ('정보보안관리 및 법규', '제3자 제공 시 고'): '제3자 제공 시 고지 및 동의 항목',
    ('정보보안관리 및 법규', '개인 정보 유출'): '개인 정보 유출 통지 사항',
    ('정보보안관리 및 법규', '개인정보 안정성'): '개인정보 안정성 확보 조치 기준',
}

# '[기무가]'처럼 대괄호로 표시되지 않은 암기용 줄임말이 설명 문장 뒤에 그냥 붙어 있는 경우.
# 괄호가 없어 자동으로 구분할 수 없으므로, 어떤 문자열을 떼어내 뱃지로 옮길지 직접 지정한다.
# (챕터, entry의 term) -> defs[0] 끝에서 떼어낼 암기용 줄임말
MANUAL_INLINE_MNEMONIC = {
    ('정보보안관리 및 법규', '정보 보호 계획 수립'): '표절기침',
    ('정보보안관리 및 법규', '기술적 보호 조치'): '내접기암백개',
}

# note 텍스트 안에서 설명이 전혀 없는 줄(원문 자체가 비어있는 플레이스홀더)만 제거.
# (챕터, note 원문 전체) -> 대체할 텍스트 (빈 문자열이면 note 전체 삭제)
MANUAL_STRIP_NOTE_LINES = {
    ('정보보안관리 및 법규', 'RTO\nRPO\nISMS'): 'ISMS',
}


def apply_manual_fixes(chapters):
    for ch in chapters:
        new_blocks = []
        for b in ch['blocks']:
            if b['type'] == 'entry' and (ch['title'], b['term']) in MANUAL_DELETE_TERMS:
                continue

            # 설명(defs)이 전혀 없는 항목은 보여줄 내용이 없으므로 제외
            if b['type'] == 'entry' and not b['defs']:
                continue

            if b['type'] == 'entry':
                mnemonic = MANUAL_INLINE_MNEMONIC.get((ch['title'], b['term']))
                if mnemonic and b['defs'] and b['defs'][0].endswith(mnemonic):
                    b['defs'][0] = b['defs'][0][:-len(mnemonic)].rstrip()
                    b['mnemonic'] = mnemonic

            if b['type'] == 'entry' and (ch['title'], b['term']) in MANUAL_MERGE_ENTRY_PAIR:
                # 다음 entry(같은 리스트의 바로 다음 블록)와 합쳐서 하나의 항목으로 만든다.
                b = dict(b)
                b['_pending_merge_target'] = MANUAL_MERGE_ENTRY_PAIR[(ch['title'], b['term'])]
                new_blocks.append(b)
                continue

            if (b['type'] == 'entry' and new_blocks and new_blocks[-1]['type'] == 'entry'
                    and '_pending_merge_target' in new_blocks[-1]):
                prev = new_blocks[-1]
                prev['term'] = prev.pop('_pending_merge_target')
                prev['defs'].extend(b['defs'])
                continue

            key = (ch['title'], b.get('text'))
            if b['type'] == 'note' and key in MANUAL_STRIP_NOTE_LINES:
                replacement = MANUAL_STRIP_NOTE_LINES[key]
                if replacement:
                    b = dict(b, text=replacement)
                else:
                    continue

            if b['type'] == 'note' and (ch['title'], b['text']) in MANUAL_DELETE_NOTES:
                continue
            if b['type'] == 'note' and any(
                    ch['title'] == c_title and b['text'].startswith(prefix)
                    for c_title, prefix in MANUAL_DELETE_NOTE_PREFIXES):
                continue

            if b['type'] == 'note' and new_blocks and new_blocks[-1]['type'] == 'entry':
                prev = new_blocks[-1]
                prev_defs0 = prev['defs'][0] if prev['defs'] else ''
                for (c_title, p_term, defs_prefix), new_term in MANUAL_MERGE_TRAILING_NOTE.items():
                    if c_title == ch['title'] and p_term == prev['term'] and prev_defs0.startswith(defs_prefix):
                        prev['term'] = new_term
                        break
                else:
                    new_blocks.append(b)
                continue

            new_blocks.append(b)

        ch['blocks'] = new_blocks
        for b in ch['blocks']:
            # 병합 상대를 못 찾은 경우를 대비한 안전 장치 (내부용 임시 키가 결과에 남지 않도록)
            b.pop('_pending_merge_target', None)


def extract_columns(page, boundaries=(180, 350)):
    words = page.extract_words(x_tolerance=2.0)
    cols = [[] for _ in range(len(boundaries) + 1)]
    for w in words:
        x = w['x0']
        idx = 0
        for b in boundaries:
            if x >= b:
                idx += 1
        cols[idx].append(w)

    col_texts = []
    for col_words in cols:
        lines = {}
        for w in col_words:
            key = round(w['top'] / 3) * 3  # 같은 줄로 묶기 (약간의 오차 허용)
            lines.setdefault(key, []).append(w)
        out_lines = []
        for key in sorted(lines):
            ws = sorted(lines[key], key=lambda w: w['x0'])
            out_lines.append(' '.join(w['text'] for w in ws))
        col_texts.append('\n'.join(out_lines))
    return col_texts


def parse_mindmap_page(page):
    """■ 섹션 / - 불릿으로 구성된 최종요약(치트시트) 페이지를 3단 컬럼으로 재구성."""
    col_texts = extract_columns(page)
    sections = []
    cur = None
    for col_text in col_texts:
        for raw_line in col_text.split('\n'):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith('■'):
                if cur:
                    sections.append(cur)
                cur = {'title': line.lstrip('■').strip(), 'items': []}
            elif cur is not None:
                cur['items'].append(line)
            # ■ 없이 시작하는 컬럼 첫 줄(섹션 헤더 인식 실패)은 버림 - 드묾
    if cur:
        sections.append(cur)
    return sections


BASE_DIR = r'C:\development\security-quiz'


def main():
    with pdfplumber.open(PDF_PATH) as pdf:
        pages = pdf.pages
        mindmap = parse_mindmap_page(pages[1])  # page index 1 == page 2

        term_pages_text = []
        for i, page in enumerate(pages):
            if i in (0, 1):  # 표지, 치트시트 페이지 제외
                continue
            term_pages_text.append((i + 1, page.extract_text(x_tolerance=2.0) or ''))

        chapters = parse_term_pages(term_pages_text)

    result = {
        'mindmap': mindmap,
        'chapters': chapters,
    }

    out_json = BASE_DIR + '\\glossary_data.json'
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    out_js = BASE_DIR + '\\glossary_data.js'
    json_str = json.dumps(result, ensure_ascii=False)
    with open(out_js, 'w', encoding='utf-8') as f:
        f.write(f'window.GLOSSARY_DATA = {json_str};\n')

    print('챕터 수:', len(chapters))
    for ch in chapters:
        n_entry = sum(1 for b in ch['blocks'] if b['type'] == 'entry')
        n_note = sum(1 for b in ch['blocks'] if b['type'] == 'note')
        print(f"  - {ch['title']!r}: entries={n_entry} notes={n_note}")
    print('mindmap 섹션 수:', len(mindmap))
    print('저장:', out_json, '/', out_js)


if __name__ == '__main__':
    main()

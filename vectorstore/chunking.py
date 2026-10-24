"""청킹 (design/retrieval-and-ui.md chunk.*). 마크다운 소제목(#~###) 단위로 먼저 나누고, 긴 구간만 글자 수로 다시 나눈다.

반환하는 각 청크에는 가장 가까운 소제목(section)과 소제목 경로(path, 예: "Model Information > Supported Languages")를 붙인다.
exclude_sections 를 주면, 소제목 경로(상위 소제목 포함)에 그 문구가 들어간 섹션(대소문자 무시 부분 일치)의 청크는 뺀다.

langchain_text_splitters 는 실제로 나눌 때만 불러온다. 이 패키지는 불러오는 순간 sentence_transformers·transformers·torch 까지
연쇄로 불러와(약 4.8초) 청킹이 필요 없는 모듈(질의응답 화면 등)의 시작을 느리게 했다 (5_성능_조사.md).
"""
import re

from common.config import setting

HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]
MD_HEADING = re.compile(r"^(?:[A-Za-z_][\w-]*: )?#{1,6}\s+(.+?)\s*$", re.M)  # "키: ### 제목" 처럼 필드 첫 줄의 제목도 포함


def text_splitter():
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    return RecursiveCharacterTextSplitter(chunk_size=setting("chunk.size"), chunk_overlap=setting("chunk.overlap"))


def is_excluded(headers, exclude_sections):
    path = " / ".join(headers).casefold()
    return any(word.casefold() in path for word in exclude_sections)


def split_markdown(text, exclude_sections=()):
    """반환: ([(청크 본문, section, path)], 제외한 청크 수)"""
    if setting("chunk.splitter") != "markdown_then_recursive":
        raise ValueError(f"지원하지 않는 chunk.splitter: {setting('chunk.splitter')}")
    from langchain_text_splitters import MarkdownHeaderTextSplitter
    sections = MarkdownHeaderTextSplitter(HEADERS, strip_headers=False).split_text(text)
    splitter = text_splitter()
    out, excluded = [], 0
    for sec in sections:
        headers = [sec.metadata[h] for _, h in HEADERS if sec.metadata.get(h)]
        title = headers[-1] if headers else ""
        pieces = [p for p in splitter.split_text(sec.page_content) if p.strip()]
        if exclude_sections and headers and is_excluded(headers, exclude_sections):
            excluded += len(pieces)
            continue
        out += [(p, title, " > ".join(headers)) for p in pieces]
    return out, excluded


def split_plain(text, section, field_names=()):
    """소제목 없는 텍스트 (예: 카드 머리말 "키: 값" 줄) 를 일반 청킹 규칙으로 나눈다. 반환: [(청크 본문, section, path)]

    path = section > 청크가 속한 필드 이름(field_names 중 "이름: " 으로 시작하는 마지막 줄) > 그 값 안의 가장 가까운 마크다운 제목.
    """
    fields = list(re.finditer(rf"^({'|'.join(map(re.escape, field_names))}): ", text, re.M)) if field_names else []
    headings = list(MD_HEADING.finditer(text))
    out, cursor = [], 0
    for piece in text_splitter().split_text(text):
        if not piece.strip():
            continue
        pos = text.find(piece, cursor)
        pos = pos if pos >= 0 else cursor
        cursor = pos + 1
        parts = [section]
        field = next((f for f in reversed(fields) if f.start() <= pos), None)
        if field:
            parts.append(field.group(1))
            head = next((h for h in reversed(headings) if field.start() <= h.start() <= pos), None)
            if head:
                parts.append(head.group(1).strip("# ").strip())
        out.append((piece, section, " > ".join(parts)))
    return out

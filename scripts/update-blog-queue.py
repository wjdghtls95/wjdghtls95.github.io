#!/usr/bin/env python3
"""
발행 완료된 포스트를 blog-queue.md의 KV 큐 → 발행됨으로 이동.
Usage: python3 scripts/update-blog-queue.py <slug>
"""
import sys
import re
from pathlib import Path
from datetime import date


def find_section(content: str, header_pattern: str) -> tuple[int, int]:
    """섹션 시작/끝 위치 반환. 없으면 (-1, -1)."""
    header_re = re.compile(rf'^## {header_pattern}', re.MULTILINE)
    match = header_re.search(content)
    if not match:
        return (-1, -1)
    next_section = re.compile(r'^## ', re.MULTILINE).search(content, match.end())
    end = next_section.start() if next_section else len(content)
    return (match.start(), end)


def update_blog_queue(slug: str) -> None:
    queue_file = Path(__file__).parent.parent / "blog-queue.md"
    if not queue_file.exists():
        print(f"blog-queue.md 없음: {queue_file}")
        sys.exit(1)

    content = queue_file.read_text(encoding="utf-8")
    draft_ref = f"`drafts/{slug}.md`"

    # KV 큐에서 해당 slug 행 찾기
    kv_start, kv_end = find_section(content, r"KV 큐.*")
    if kv_start == -1:
        print("KV 큐 섹션 없음")
        sys.exit(1)

    kv_section = content[kv_start:kv_end]

    row_re = re.compile(
        r'^\|[^|]*\|\s*' + re.escape(draft_ref) + r'\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$',
        re.MULTILINE
    )
    row_match = row_re.search(kv_section)

    if not row_match:
        print(f"'{slug}'을 KV 큐에서 찾을 수 없음 (이미 처리됐거나 KV에만 존재)")
        sys.exit(0)

    title = row_match.group(1).strip()
    matched_row = row_match.group(0)

    # KV 큐에서 행 제거
    updated = content.replace(matched_row + '\n', '', 1)
    if updated == content:
        updated = content.replace(matched_row, '', 1)

    # 발행됨 섹션에 추가
    pub_start, pub_end = find_section(updated, "발행됨")
    if pub_start == -1:
        print("발행됨 섹션 없음")
        sys.exit(1)

    pub_section = updated[pub_start:pub_end]

    nums = [int(m.group(1)) for m in re.finditer(r'^\|\s*(\d+)\s*\|', pub_section, re.MULTILINE)]
    next_num = max(nums) + 1 if nums else 1

    today = date.today().strftime("%Y-%m-%d")
    new_row = f"| {next_num} | {title} | {slug} | {today} |"

    # 발행됨 섹션의 마지막 테이블 행 뒤에 삽입
    table_rows = list(re.finditer(r'^\|.*\|$', pub_section, re.MULTILINE))
    if table_rows:
        insert_abs = pub_start + table_rows[-1].end()
        updated = updated[:insert_abs] + '\n' + new_row + updated[insert_abs:]
    else:
        # 테이블이 비어있으면 구분선 찾아서 뒤에 추가
        sep = re.search(r'\|[-\s|]+\|', pub_section)
        if sep:
            insert_abs = pub_start + sep.end()
            updated = updated[:insert_abs] + '\n' + new_row + updated[insert_abs:]

    # _Updated 날짜 갱신
    updated = re.sub(r'_Updated: \d{4}-\d{2}-\d{2}_', f'_Updated: {today}_', updated)

    queue_file.write_text(updated, encoding="utf-8")
    print(f"✅ '{title}' ({slug}) → 발행됨 ({today})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: update-blog-queue.py <slug>")
        sys.exit(1)
    update_blog_queue(sys.argv[1])

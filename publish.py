"""
Stage 2: 发布已审核草稿
- 输入 review_id（来自飞书卡片上你复制的那个）
- 读 pending/<review_id>.json
- 调 GP API 发布
- 把文件从 pending/ 移到 published/
- 飞书推送结果
"""
import os
import sys
import json
import shutil
import time
from common import (
    PACKAGE_NAME, get_service, push_text,
)

PENDING_DIR = 'pending'
PUBLISHED_DIR = 'published'


def main():
    if len(sys.argv) < 2:
        print("用法: python publish.py <review_id>")
        sys.exit(1)

    review_id = sys.argv[1].strip()
    pending_path = os.path.join(PENDING_DIR, f'{review_id}.json')

    if not os.path.exists(pending_path):
        msg = f"❌ 找不到待审核草稿: {review_id}\n（请检查 pending/ 目录，或确认 review_id 是否正确）"
        print(msg)
        push_text(msg)
        sys.exit(1)

    with open(pending_path, 'r', encoding='utf-8') as f:
        draft = json.load(f)

    reply_text = draft['reply_original']
    print(f"发布: {review_id[:10]} | ⭐{draft['star']} | {len(reply_text)} 字符")
    print(f"内容预览: {reply_text[:120]}...")

    service = get_service()
    try:
        service.reviews().reply(
            packageName=PACKAGE_NAME,
            reviewId=review_id,
            body={'replyText': reply_text},
        ).execute()
    except Exception as e:
        err = f"❌ 发布失败 {review_id[:10]}: {e}"
        print(err)
        push_text(err)
        sys.exit(1)

    # 移动文件到 published/
    draft['published_at'] = int(time.time())
    published_path = os.path.join(PUBLISHED_DIR, f'{review_id}.json')
    with open(published_path, 'w', encoding='utf-8') as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    os.remove(pending_path)
    print(f"已归档: {published_path}")

    push_text(
        f"✅ 已发布回复\n"
        f"Review: {review_id[:10]}\n"
        f"⭐{draft['star']} | {len(reply_text)} 字符\n"
        f"---\n{reply_text[:200]}"
    )


if __name__ == "__main__":
    main()

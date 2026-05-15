"""
Stage 2: 发布已审核草稿
- 必填: review_id
- 可选: override_reply（自定义回复内容；填中文会自动翻成原评论语种）
- 不传 override 就用原草稿；传了就用 override 覆盖
"""
import os
import sys
import json
import time
from common import (
    PACKAGE_NAME, get_service, push_text,
    smart_truncate, match_language_of, publish_reply,
)

PENDING_DIR = 'pending'
PUBLISHED_DIR = 'published'


def main():
    if len(sys.argv) < 2:
        print("用法: python publish.py <review_id> [override_reply]")
        sys.exit(1)

    review_id = sys.argv[1].strip()
    override_reply = sys.argv[2].strip() if len(sys.argv) > 2 else ""

    pending_path = os.path.join(PENDING_DIR, f'{review_id}.json')

    if not os.path.exists(pending_path):
        msg = f"❌ 找不到待审核草稿: {review_id}\n（请检查 pending/ 目录，或确认 review_id 是否正确）"
        print(msg)
        push_text(msg)
        sys.exit(1)

    with open(pending_path, 'r', encoding='utf-8') as f:
        draft = json.load(f)

    # 决定要发的内容
    if override_reply:
        print(f"检测到 override_reply（{len(override_reply)} 字符），将覆盖原草稿")
        # 自动转成原评论语种（如果已经同语种，AI 会原样返回）
        original_text = draft.get('text_original', '')
        final_reply = match_language_of(override_reply, original_text)

        # 如果翻译后跟输入完全一致，说明语种本来就匹配
        if final_reply.strip() == override_reply.strip():
            print(f"  语种已匹配原评论，无需翻译")
        else:
            print(f"  已翻译: {override_reply[:50]}... → {final_reply[:50]}...")

        # 截断到 GP 350 字符上限
        final_reply = smart_truncate(final_reply)

        # 把原草稿和 override 都存进 json 留底
        draft['reply_original_before_override'] = draft['reply_original']
        draft['override_input'] = override_reply
        draft['reply_original'] = final_reply
    else:
        final_reply = draft['reply_original']

    print(f"发布: {review_id[:10]} | ⭐{draft['star']} | {len(final_reply)} 字符")
    print(f"内容预览: {final_reply[:120]}...")

    service = get_service()
    ok = publish_reply(service, review_id, final_reply)
    if not ok:
        err = f"❌ 发布失败 {review_id[:10]}"
        push_text(err)
        sys.exit(1)

    # 归档：pending -> published
    draft['published_at'] = int(time.time())
    draft['auto_published'] = False
    if override_reply:
        draft['was_overridden'] = True

    published_path = os.path.join(PUBLISHED_DIR, f'{review_id}.json')
    with open(published_path, 'w', encoding='utf-8') as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    os.remove(pending_path)
    print(f"已归档: {published_path}")

    tag = "（已修改）" if override_reply else ""
    push_text(
        f"✅ 已发布回复{tag}\n"
        f"Review: {review_id[:10]}\n"
        f"⭐{draft['star']} | {len(final_reply)} 字符\n"
        f"---\n{final_reply[:200]}"
    )


if __name__ == "__main__":
    main()

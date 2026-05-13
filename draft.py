"""
Stage 1: 生成草稿
- 拉 Google Play 评论
- 筛出未回复 / 有追评的
- 翻译原文 + AI 生成回复 + 翻译回复
- 存到 pending/<review_id>.json
- 推飞书卡片
- 不发布
"""
import os
import sys
import json
import time
from common import (
    PACKAGE_NAME, get_service, get_skill_pack,
    translate_to_zh, generate_ai_reply,
    push_text, push_draft_card,
)

PENDING_DIR = 'pending'
PUBLISHED_DIR = 'published'
REJECTED_DIR = 'rejected'


def ensure_dirs():
    for d in (PENDING_DIR, PUBLISHED_DIR, REJECTED_DIR):
        os.makedirs(d, exist_ok=True)
        # 加 .gitkeep 让空目录也能 commit
        keep = os.path.join(d, '.gitkeep')
        if not os.path.exists(keep):
            with open(keep, 'w') as f:
                f.write('')


def already_handled(review_id):
    """已在 pending / published / rejected 中的不再重复生成。"""
    for d in (PENDING_DIR, PUBLISHED_DIR, REJECTED_DIR):
        if os.path.exists(os.path.join(d, f'{review_id}.json')):
            return True
    return False


def save_draft(draft):
    path = os.path.join(PENDING_DIR, f"{draft['review_id']}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    print(f"草稿已存盘: {path}")


def main():
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    ensure_dirs()

    service = get_service()
    skill_pack = get_skill_pack()
    time_threshold = int(time.time()) - (days_back * 24 * 60 * 60)

    print(f"启动：回溯 {days_back} 天 | 包名: {PACKAGE_NAME}")

    next_token = None
    drafts = []
    page = 0

    while True:
        page += 1
        result = service.reviews().list(
            packageName=PACKAGE_NAME, maxResults=100, token=next_token
        ).execute()
        reviews = result.get('reviews', [])
        next_token = result.get('nextPageToken')

        if not reviews:
            break
        print(f"扫描第 {page} 页（{len(reviews)} 条）")

        for r in reviews:
            comments = r.get('comments', [])
            if not comments:
                continue
            user_c = comments[0]['userComment']
            dev_c = comments[1]['developerComment'] if len(comments) > 1 else None

            user_time = int(user_c['lastModified']['seconds'])
            dev_time = int(dev_c['lastModified']['seconds']) if dev_c else 0

            # 核心判断：在窗口内 且 用户最新动作晚于我们的回复
            if not (user_time >= time_threshold and user_time > dev_time):
                continue

            review_id = r['reviewId']

            # 去重：之前已经处理过的就跳过
            if already_handled(review_id):
                print(f"跳过（已处理）: {review_id[:10]}")
                continue

            text = (user_c.get('text') or '').strip()
            if not text:
                print(f"跳过（空文本）: {review_id[:10]}")
                continue

            star = user_c.get('starRating', 0)
            is_update = bool(dev_c)

            print(f"命中: {review_id[:10]} {'(追评)' if is_update else ''} ⭐{star}")

            # 翻译原文
            text_zh = translate_to_zh(text)

            # 生成回复
            reply = generate_ai_reply(text, star, skill_pack, is_update)
            if not reply:
                print(f"  生成失败，跳过")
                continue

            # 翻译回复（用于审核时核对内容）
            reply_zh = translate_to_zh(reply)

            draft = {
                'review_id': review_id,
                'star': star,
                'is_update': is_update,
                'user_time': user_time,
                'dev_time': dev_time,
                'text_original': text,
                'text_zh': text_zh,
                'reply_original': reply,
                'reply_zh': reply_zh,
                'created_at': int(time.time()),
            }
            save_draft(draft)
            push_draft_card(draft)
            drafts.append(draft)
            time.sleep(0.5)  # 节流，防止 OpenRouter 限流

        # 翻页停止条件
        last_item_time = int(reviews[-1]['comments'][0]['userComment']['lastModified']['seconds'])
        if last_item_time < time_threshold or not next_token or page >= 10:
            break

    # 收尾汇总
    if drafts:
        summary = f"📝 生成 {len(drafts)} 条草稿待审核：\n" + "\n".join(
            [f"- {d['review_id'][:10]} ⭐{d['star']}" for d in drafts]
        )
        push_text(summary)
    else:
        push_text("📭 本次扫描无新评论需要回复。")

    print(f"完成：本次新增 {len(drafts)} 条草稿。")


if __name__ == "__main__":
    main()

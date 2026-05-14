"""
Stage 1: 生成草稿 + 分流
- 拉 Google Play 评论
- 筛出未回复 / 有追评的
- 翻译原文 + AI 生成回复 + 翻译回复
- 分流：
    · ≥4 星且非追评 → 直接发布，存到 published/
    · ≤3 星 或 追评 → 存到 pending/，推飞书审核卡片
"""
import os
import sys
import json
import time
from common import (
    PACKAGE_NAME, get_service, get_skill_pack,
    translate_to_zh, generate_ai_reply,
    push_text, push_draft_card, publish_reply,
)

PENDING_DIR = 'pending'
PUBLISHED_DIR = 'published'
REJECTED_DIR = 'rejected'

# 自动发布阈值：星级 >= 此值 且 非追评 才直发
AUTO_PUBLISH_MIN_STAR = 4


def ensure_dirs():
    for d in (PENDING_DIR, PUBLISHED_DIR, REJECTED_DIR):
        os.makedirs(d, exist_ok=True)
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


def save_to(directory, draft):
    path = os.path.join(directory, f"{draft['review_id']}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    return path


def should_auto_publish(star, is_update):
    """≥AUTO_PUBLISH_MIN_STAR 星 且 非追评 才直发。"""
    return star >= AUTO_PUBLISH_MIN_STAR and not is_update


def main():
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    ensure_dirs()

    service = get_service()
    skill_pack = get_skill_pack()
    time_threshold = int(time.time()) - (days_back * 24 * 60 * 60)

    print(f"启动：回溯 {days_back} 天 | 包名: {PACKAGE_NAME} | 直发阈值: ⭐≥{AUTO_PUBLISH_MIN_STAR}")

    next_token = None
    auto_published = []
    auto_failed = []
    pending_review = []
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
        print(f"扫描第 {page} 页({len(reviews)} 条)")

        for r in reviews:
            comments = r.get('comments', [])
            if not comments:
                continue
            user_c = comments[0]['userComment']
            dev_c = comments[1]['developerComment'] if len(comments) > 1 else None

            user_time = int(user_c['lastModified']['seconds'])
            dev_time = int(dev_c['lastModified']['seconds']) if dev_c else 0

            if not (user_time >= time_threshold and user_time > dev_time):
                continue

            review_id = r['reviewId']

            if already_handled(review_id):
                print(f"跳过(已处理): {review_id[:10]}")
                continue

            text = (user_c.get('text') or '').strip()
            if not text:
                print(f"跳过(空文本): {review_id[:10]}")
                continue

            star = user_c.get('starRating', 0)
            is_update = bool(dev_c)

            tag = '(追评)' if is_update else ''
            print(f"命中: {review_id[:10]} {tag} star={star}")

            text_zh = translate_to_zh(text)

            reply = generate_ai_reply(text, star, skill_pack, is_update)
            if not reply:
                print(f"  生成失败，跳过")
                continue

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

            # ===== 分流 =====
            if should_auto_publish(star, is_update):
                print(f"  -> 自动发布")
                ok = publish_reply(service, review_id, reply)
                if ok:
                    draft['published_at'] = int(time.time())
                    draft['auto_published'] = True
                    save_to(PUBLISHED_DIR, draft)
                    auto_published.append(draft)
                else:
                    print(f"  发布失败，转入待审核")
                    save_to(PENDING_DIR, draft)
                    push_draft_card(draft)
                    auto_failed.append(draft)
            else:
                reason = '追评' if is_update else f'star={star}'
                print(f"  -> 待审核({reason})")
                save_to(PENDING_DIR, draft)
                push_draft_card(draft)
                pending_review.append(draft)

            time.sleep(0.5)

        # 翻页停止
        last_item_time = int(reviews[-1]['comments'][0]['userComment']['lastModified']['seconds'])
        if last_item_time < time_threshold or not next_token or page >= 10:
            break

    # 收尾汇总
    total = len(auto_published) + len(pending_review) + len(auto_failed)
    if total == 0:
        push_text("📭 本次扫描无新评论需要回复。")
    else:
        lines = [f"📊 本次共处理 {total} 条评论："]
        if auto_published:
            lines.append(f"\n✅ 已自动发布 {len(auto_published)} 条（⭐≥{AUTO_PUBLISH_MIN_STAR}）：")
            lines += [f"  · {d['review_id'][:10]} ⭐{d['star']}" for d in auto_published]
        if pending_review:
            lines.append(f"\n📝 待审核 {len(pending_review)} 条（差评/中评/追评）：")
            lines += [f"  · {d['review_id'][:10]} ⭐{d['star']}{' 追评' if d['is_update'] else ''}"
                      for d in pending_review]
        if auto_failed:
            lines.append(f"\n⚠️ 自动发布失败转待审核 {len(auto_failed)} 条：")
            lines += [f"  · {d['review_id'][:10]} ⭐{d['star']}" for d in auto_failed]
        push_text("\n".join(lines))

    print(f"完成：自动发布 {len(auto_published)} | 待审核 {len(pending_review)} | 失败转人工 {len(auto_failed)}")


if __name__ == "__main__":
    main()

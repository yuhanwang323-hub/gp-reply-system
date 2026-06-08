"""
公共模块：被 draft.py 和 publish.py 共享
- Google Play service 鉴权
- OpenRouter AI 调用（生成 + 翻译）
- 飞书推送（文本 + 卡片）
- skill.txt 读取
- 字符截断
"""
import os
import json
import time
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ================= 配置 =================
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK_URL')
AI_KEY = os.environ.get('AI_REPLY_KEY')
AI_URL = "https://zenmux.ai/api/v1/chat/completions"
GEMINI_MODEL = "google/gemini-3.5-flash"

# 仓库地址，用于卡片里生成跳转链接
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '')  # GitHub Actions 自动注入，例如 "user/repo"


# ================= GP 鉴权 =================
def get_service():
    key_content = os.environ.get('GP_JSON_KEY')
    if not key_content:
        raise ValueError("GP_JSON_KEY 环境变量未设置")
    info = json.loads(key_content)
    creds = service_account.Credentials.from_service_account_info(info)
    return build('androidpublisher', 'v3', credentials=creds)


# ================= GP 发布 =================
def publish_reply(service, review_id, reply_text):
    """调 GP API 发布回复。成功返回 True，失败返回 False（不抛出）。"""
    try:
        service.reviews().reply(
            packageName=PACKAGE_NAME,
            reviewId=review_id,
            body={'replyText': reply_text},
        ).execute()
        return True
    except Exception as e:
        print(f"发布失败 {review_id[:10]}: {e}")
        return False


# ================= 话术包 =================
def get_skill_pack():
    file_path = 'skill.txt'
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "你是一名专业的 App 客服，请用礼貌、专业的语气回复用户。"


# ================= 字符截断 =================
def smart_truncate(content, limit=345):
    """在限制字数内优先保留完整句子。"""
    if len(content) <= limit:
        return content
    truncated = content[:limit]
    last_punctuation = -1
    for char in ['。', '！', '？', '.', '!', '?']:
        pos = truncated.rfind(char)
        if pos > last_punctuation:
            last_punctuation = pos
    if last_punctuation != -1:
        return truncated[:last_punctuation + 1]
    last_space = truncated.rfind(' ')
    if last_space != -1:
        return truncated[:last_space] + "..."
    return truncated + "..."


# ================= OpenRouter 调用 =================
def call_ai(prompt, temperature=0.3):
    """通用 LLM 调用，失败返回 None。"""
    if not AI_KEY:
        print("AI 调用失败: AI_REPLY_KEY 未设置")
        return None
    try:
        res = requests.post(
            AI_URL,
            headers={"Authorization": f"Bearer {AI_KEY}"},
            json={
                "model": GEMINI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
            timeout=60,
        )
        if res.status_code != 200:
            print(f"AI 调用失败: HTTP {res.status_code}, 响应: {res.text[:300]}")
            return None
        data = res.json()
        if 'choices' not in data or not data['choices']:
            print(f"AI 调用失败: 响应无 choices - {data}")
            return None
        return data['choices'][0]['message']['content'].strip()
    except requests.exceptions.RequestException as e:
        print(f"AI 调用失败: 网络异常 - {e}")
        return None
    except Exception as e:
        print(f"AI 调用失败: {type(e).__name__} - {e}")
        return None


# ================= 翻译 =================
def translate_to_zh(text):
    """把任意语种的文本翻译成中文。如果已经是中文，原样返回。"""
    if not text or not text.strip():
        return ""
    prompt = f"""把下面这段文本翻译成中文。如果原文已经是中文，原样返回，不要改动。
只输出翻译结果，不要加任何说明、标点之外的引号、前缀、后缀。

原文：
{text}
"""
    result = call_ai(prompt, temperature=0.1)
    return result if result else "[翻译失败]"


def match_language_of(text, reference_text):
    """把 text 转成 reference_text 的语种。
    如果 text 已经和 reference_text 同语种，原样返回。
    用于：人工填的中文 override 文本，自动翻译成原评论的语种。
    """
    if not text or not text.strip():
        return ""
    prompt = f"""请判断下面【目标文本】和【参考文本】是否是同一语种。
- 如果是同一语种：原样返回【目标文本】，一个字也不要改。
- 如果不是同一语种：把【目标文本】翻译成【参考文本】的语种，保持原意和语气。

只输出最终结果，不要加任何说明、引号、前缀、后缀。

【参考文本】（这是用户原评论，作为目标语种）：
{reference_text}

【目标文本】（需要确保和参考文本同语种）：
{text}
"""
    result = call_ai(prompt, temperature=0.1)
    return result if result else text  # 翻译失败就用原文兜底


# ================= 生成回复 =================
def generate_ai_reply(text, star, skill_pack, is_update=False):
    update_note = "【注意：这是用户的追评，请针对其更新的内容回答，并感谢其反馈更新】" if is_update else ""
    prompt = f"""
    技能包：
{skill_pack}
    任务：{update_note}
    用户评价（{star}星）: {text}
    要求：
    1.相同语种回复
    2.严禁超过350字符。
    3.直接输出内容。
    4.如果内容过多，请优先保留核心解决方案，删掉客套话。
    5.回复好评不要过于模板同质化，可以适当增加一些个性化的内容。
    6.用户遇到问题就要让用户去support@fantachat.ai反馈，这很重要！
    """
    content = call_ai(prompt, temperature=0.3)
    return smart_truncate(content) if content else None


# ================= 飞书推送 =================
def push_text(text):
    """简单文本推送。自动加 [GP] 前缀以满足飞书关键词校验。"""
    if not FEISHU_WEBHOOK:
        return
    # 如果消息里已经有 [GP] 就不重复加
    if not text.startswith('[GP]'):
        text = f'[GP] {text}'
    try:
        requests.post(
            FEISHU_WEBHOOK,
            json={"msg_type": "text", "content": {"text": text}},
            timeout=20,
        )
    except Exception as e:
        print(f"飞书推送失败: {e}")


def push_draft_card(draft):
    """把一条草稿推成飞书卡片。

    draft 字段:
        review_id, star, is_update,
        text_original, text_zh,
        reply_original, reply_zh
    """
    if not FEISHU_WEBHOOK:
        return

    stars = "⭐" * int(draft.get('star') or 0)
    tag = "【追评】" if draft.get('is_update') else "【新评】"

    # publish workflow 的入口链接（你点进去填 review_id 手动跑）
    if GITHUB_REPO:
        publish_url = f"https://github.com/{GITHUB_REPO}/actions/workflows/publish.yml"
    else:
        publish_url = "https://github.com"

    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text",
                          "content": f"[GP] {tag} {stars}  待审核"},
                "template": "blue" if (draft.get('star') or 0) >= 4 else "orange",
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {"is_short": False, "text": {
                            "tag": "lark_md",
                            "content": f"**Review ID（复制这串去触发发布）：**\n`{draft['review_id']}`"
                        }},
                    ],
                },
                {"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md",
                                        "content": "**用户评论（原文）：**"}},
                {"tag": "div", "text": {"tag": "plain_text",
                                        "content": draft.get('text_original', '(空)') or '(空)'}},
                {"tag": "div", "text": {"tag": "lark_md",
                                        "content": "**用户评论（中文）：**"}},
                {"tag": "div", "text": {"tag": "plain_text",
                                        "content": draft.get('text_zh', '') or '(无)'}},
                {"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md",
                                        "content": "**AI 草稿（将发出）：**"}},
                {"tag": "div", "text": {"tag": "plain_text",
                                        "content": draft.get('reply_original', '')}},
                {"tag": "div", "text": {"tag": "lark_md",
                                        "content": "**AI 草稿（中文核对）：**"}},
                {"tag": "div", "text": {"tag": "plain_text",
                                        "content": draft.get('reply_zh', '') or '(无)'}},
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "去 Actions 发布"},
                            "type": "primary",
                            "url": publish_url,
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "驳回（仓库里把文件挪到 rejected/）"},
                            "type": "default",
                            "url": f"https://github.com/{GITHUB_REPO}/tree/main/pending" if GITHUB_REPO else "https://github.com",
                        },
                    ],
                },
            ],
        },
    }
    try:
        requests.post(FEISHU_WEBHOOK, json=card, timeout=20)
    except Exception as e:
        print(f"飞书卡片推送失败: {e}")

# GP 自动回复（人工审核版）

在原版基础上增加：**人工审核**（飞书卡片）+ **双语翻译**（OpenRouter 复用）。

## 跟原版的差别

原版是「一键跑完，AI 写完直接发到 Google Play」。
这版拆成了**两个阶段**：

| 阶段 | 触发方式 | 做什么 |
| --- | --- | --- |
| Stage 1: Generate Drafts | 手动跑 workflow，输入回溯天数 | 拉评论、翻译原文、AI 生成回复、翻译回复、存草稿到 `pending/`、推飞书卡片 |
| Stage 2: Publish Reply | 手动跑 workflow，输入 review_id | 读 `pending/<id>.json`，调 GP API 发布，文件移到 `published/` |

驳回不需要触发任何 workflow——直接去仓库把 `pending/<id>.json` 拖到 `rejected/`（或者删掉）即可。

## 工作流程（你的实际操作）

1. 去 Actions → Stage 1 → Run workflow，输入 7（回溯 7 天）。
2. 等飞书来卡片，每条新评论一张。卡片里有：
   - 用户评论：原文 + 中文翻译
   - AI 草稿：原文 + 中文翻译（核对会不会发出莫名其妙的话）
   - Review ID（一长串字符，复制下来）
3. 看着没问题 → 去 Actions → Stage 2 → Run workflow，粘贴 review_id，跑。
   看着不行 → 仓库里把 `pending/<id>.json` 删掉或拖到 `rejected/`。
4. Stage 2 跑完会推一条飞书消息「✅ 已发布」。

## 一次部署需要做的事

### 仓库结构
```
.
├── .github/workflows/
│   ├── draft.yml       # Stage 1
│   └── publish.yml     # Stage 2
├── common.py           # 公共模块（GP/AI/翻译/飞书）
├── draft.py            # Stage 1 入口
├── publish.py          # Stage 2 入口
├── skill.txt           # 6000字话术包（沿用原版）
├── requirements.txt
├── pending/            # 待审核草稿（自动创建）
├── published/          # 已发布存档（自动创建，同时用作去重）
└── rejected/           # 驳回存档（自动创建）
```

### Secrets（和原版一样）
仓库 → Settings → Secrets and variables → Actions：
- `GP_JSON_KEY` —— Google Play 服务账号 JSON
- `PACKAGE_NAME` —— App 包名
- `AI_REPLY_KEY` —— OpenRouter Key
- `FEISHU_WEBHOOK_URL` —— 飞书机器人 webhook

### Workflow 权限
仓库 → Settings → Actions → General → **Workflow permissions** → 勾选 **Read and write permissions**。
（不勾选的话，draft.yml 没法 commit `pending/` 回仓库。）

## 一些细节

**去重**：`already_handled()` 会检查 `pending/`、`published/`、`rejected/` 三个目录，任一存在 `<review_id>.json` 就跳过。所以同一条评论不会反复生成草稿。但是！如果用户**追评**了，`review_id` 不变，会被判定为已处理——这个版本目前不区分追评，要支持追评的话，得在文件名里带上 `user_time` 时间戳，或者每次拿到追评就把旧的 published 移走。先用一段时间看追评频率再决定。

**翻译双调**：每条命中都会调两次 OpenRouter（一次译原文、一次译回复），加上生成回复本身一次，一条评论 = 3 次 LLM 调用。看你 OpenRouter 的额度。

**驳回的两种做法**：
- 偷懒版：直接在 GitHub 网页上点 `pending/<id>.json` 的删除按钮，commit 一下。
- 留底版：把文件挪到 `rejected/`（GitHub 网页支持 rename 时改路径）。

**飞书卡片的两个按钮**都是跳转链接，不是真的"点了就执行"。这是 GitHub Actions 体系下的局限，要真按钮即时生效得起常驻服务（路线 B），现在没必要。

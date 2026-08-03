#!/usr/bin/env bash
# sync_upstream.sh — 从 upstream 拉取同步更新，自动 stash/pop，有冲突时提示
set -euo pipefail

REMOTE="${1:-upstream}"
BRANCH="${2:-main}"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# 检查 remote 是否存在
if ! git remote get-url "$REMOTE" &>/dev/null; then
    err "Remote '$REMOTE' 不存在。"
    echo ""
    echo "请先添加 upstream remote："
    echo "  git remote add upstream https://github.com/ZhuLinsen/daily_stock_analysis.git"
    echo ""
    echo "用法: $0 [remote] [branch]"
    echo "  remote  — upstream remote 名称，默认 upstream"
    echo "  branch  — 要同步的分支，默认 main"
    exit 1
fi

REMOTE_URL=$(git remote get-url "$REMOTE")
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

info "Remote: $REMOTE ($REMOTE_URL)"
info "目标分支: $BRANCH"
info "当前分支: $CURRENT_BRANCH"
echo ""

# 检查工作区是否有改动（tracked + untracked 都算）
STASHED=false
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null || \
   [ -n "$(git ls-files --others --exclude-standard 2>/dev/null)" ]; then
    info "工作区有未提交改动，自动 stash ..."
    git stash push --include-untracked -m "auto-stash before sync_upstream $(date +%Y%m%d_%H%M%S)"
    STASHED=true
    ok "改动已暂存。"
    echo ""
fi

# 清理函数：如果 stash 了但中途失败，确保 pop 回去
restore_on_exit() {
    if [ "$STASHED" = true ]; then
        echo ""
        info "恢复暂存的改动 ..."
        if git stash pop 2>/dev/null; then
            ok "改动已恢复。"
        else
            warn "stash pop 有冲突，请手动执行: git stash pop"
        fi
    fi
}
trap restore_on_exit EXIT

# 拉取 upstream 最新内容
info "正在 fetch $REMOTE/$BRANCH ..."
if ! git fetch "$REMOTE" "$BRANCH"; then
    err "Fetch 失败，请检查网络或 remote URL。"
    exit 1
fi

UPSTREAM_COMMIT=$(git rev-parse "$REMOTE/$BRANCH" 2>/dev/null || true)
LOCAL_COMMIT=$(git rev-parse HEAD)

if [ "$UPSTREAM_COMMIT" = "$LOCAL_COMMIT" ]; then
    ok "本地已是最新，无需同步。"
    exit 0
fi

# 显示即将合并的 commits
COMMITS_AHEAD=$(git rev-list --count HEAD.."$REMOTE/$BRANCH" 2>/dev/null || echo "0")
info "Upstream 领先 $COMMITS_AHEAD 个 commit。"
echo ""
echo "--- 最近的 upstream commits ---"
git log --oneline --decorate -10 HEAD.."$REMOTE/$BRANCH" 2>/dev/null || true
echo "---"
echo ""

# 如果不在目标分支上，先切换
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
    info "切换到 $BRANCH ..."
    git checkout "$BRANCH"
fi

# 尝试 merge，检测冲突
info "正在 merge $REMOTE/$BRANCH ..."
MERGE_OUTPUT=$(git merge "$REMOTE/$BRANCH" --no-edit 2>&1) || MERGE_STATUS=$? || MERGE_STATUS=0

if [ "${MERGE_STATUS:-0}" -eq 0 ]; then
    ok "同步成功，无冲突。"
    echo ""
    git log --oneline -5
else
    # 检查是否有冲突
    CONFLICT_FILES=$(git diff --name-only --diff-filter=U 2>/dev/null || true)
    if [ -n "$CONFLICT_FILES" ]; then
        err "发现冲突！以下文件需要手动解决："
        echo ""
        git diff --name-only --diff-filter=U | while read -r f; do
            echo -e "  ${RED}$f${NC}"
        done
        echo ""
        echo "--- 冲突摘要 ---"
        git diff --stat --diff-filter=U 2>/dev/null || true
        echo "---"
        echo ""
        warn "请手动解决冲突后执行："
        echo "  1. 编辑上方列出的冲突文件"
        echo "  2. git add <已解决的文件>"
        echo "  3. git commit"
        echo ""
        echo "如果想放弃本次 merge："
        echo "  git merge --abort"
        exit 1
    else
        err "Merge 失败（非冲突原因）："
        echo "$MERGE_OUTPUT"
        exit 1
    fi
fi

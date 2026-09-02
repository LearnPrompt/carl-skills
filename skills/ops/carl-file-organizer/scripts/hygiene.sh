#!/usr/bin/env bash
# Repository hygiene: nothing that ships should carry one person's machine, one
# person's private project names, or borrowed vocabulary.
#
# The patterns live in this one file, and this file excludes itself from every
# search.  Spelling them inline in the CI workflow made the workflow match
# itself, so the check failed on a clean tree.
#
# Two scopes, because the four rules are not the same kind of rule:
#
#   repo   the whole collection.  A private path or an unattributed source is a
#          publishing problem wherever it sits, so every skill is searched.
#   skill  this skill's own folder.  Traffic-light wording and the product names
#          this tool grew out of are house style here; another skill in the
#          collection has its own history and its own vocabulary.
#
# tests/ is left out of the private-path rule on purpose.  Nothing under tests/
# is installed or published, and a test that proves a path gets redacted has to
# spell out the path being redacted.  This rule protects what people receive.
#
# Usage: bash skills/ops/carl-file-organizer/scripts/hygiene.sh
#        (exit 0 clean, exit 1 with the offending lines; run it from anywhere)

set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
skill_dir="$(cd "$here/.." && pwd)"
repo_root="$(cd "$skill_dir/../../.." && pwd)"
cd "$repo_root"

skill_rel="${skill_dir#"$repo_root"/}"

COMMON=(-r -n -E
  --exclude-dir=.git
  --exclude-dir=fixtures
  --exclude-dir=__pycache__
  --exclude-dir=node_modules
  --exclude-dir=.venv
  --exclude-dir=dist
  --exclude-dir=build
  --exclude-dir=.gstack
  --exclude=hygiene.sh
)

failed=0

report() {
  echo "::error::$1"
  failed=1
}

# 1. No absolute home directories and no one machine's account name, anywhere
#    that ships.  See the note above about tests/.
#
#    The path pattern wants /Users/ followed by something that looks like a real
#    account, so code and prose that handle the prefix itself -- a redaction
#    regex, a startswith check, a sentence listing the shapes -- read as what
#    they are.  Two rules make that work: an account name starts with a letter
#    or digit, and it is longer than one character.  Which makes /Users/x the
#    house placeholder: use it when a document has to show the shape.
if grep "${COMMON[@]}" --exclude-dir=tests '/Users/[A-Za-z0-9_-]{2,}|carl2077|\$CODEX_HOME' .; then
  report "private path pattern found; write \$HOME/... instead, or /Users/x when a document has to show the shape"
fi

# 2. The acknowledgements table in the READMEs is the only place a source is
#    named, and that holds for every skill in the collection.
matches=$(grep "${COMMON[@]}" -l '卡兹克|Khazix|storage-analyzer' . 2>/dev/null || true)
if [ -n "$matches" ]; then
  outside=$(printf '%s\n' "$matches" | grep -vE '(^|/)README(\.en)?\.md$' || true)
  if [ -n "$outside" ]; then
    report "source named outside the README acknowledgements: $outside"
  fi
fi

# 3. Borrowed traffic-light vocabulary, in this skill's own writing.
if grep "${COMMON[@]}" '红灯|黄灯|绿灯' "$skill_rel"; then
  report "traffic-light terminology found"
fi

# 4. Private product and service names from the notes this tool grew out of,
#    in this skill's own writing.
if grep "${COMMON[@]}" -i 'tikhub|deepseek|goodcase|订阅链接' "$skill_rel"; then
  report "private product name found; use an invented name instead"
fi

if [ "$failed" -eq 0 ]; then
  echo "hygiene: clean"
fi
exit "$failed"

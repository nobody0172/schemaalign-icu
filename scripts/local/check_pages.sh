#!/usr/bin/env bash
# ICASSP 版面核对。CFP: 正文(含图与参考文献)最多 4 页; 可选第 5 页**只能**放
# 参考文献、经费致谢、以及 Compliance with Ethical Standards 声明。
# 判据: 编号小节 1..N 中, 除 REFERENCES / COMPLIANCE / ACKNOWLEDG* 之外的技术小节
#       不得出现在第 5 页; 且总页数 <= 5。
set -uo pipefail
PDF="${1:-main.pdf}"
N=$(pdfinfo "$PDF" | awk '/^Pages/{print $2}')
echo "pages = $N"
[ "$N" -gt 5 ] && { echo "FAIL: more than 5 pages"; exit 1; }
BAD=0
for i in $(seq 1 "$N"); do
  H=$(pdftotext -f $i -l $i "$PDF" - | grep -oE '^[0-9]+\. [A-Z][A-Z ]+' | sed 's/^[0-9]*\. //')
  [ -n "$H" ] && echo "  p$i: $(echo "$H" | tr '\n' '|')"
  if [ "$i" -ge 5 ]; then
    while IFS= read -r h; do
      [ -z "$h" ] && continue
      case "$h" in
        REFERENCES*|COMPLIANCE*|ACKNOWLEDG*) ;;
        *) echo "  FAIL: technical section '$h' on page $i"; BAD=1;;
      esac
    done <<< "$H"
    # 第 5 页在首个允许小节之前不得有正文
    PRE=$(pdftotext -f $i -l $i "$PDF" - | awk '/^[0-9]+\. (REFERENCES|COMPLIANCE|ACKNOWLEDG)/{exit} {n+=length($0)+1} END{print n+0}')
    [ "$PRE" -gt 0 ] && { echo "  FAIL: ~$PRE chars of body precede the allowed sections on page $i"; BAD=1; }
  fi
done
[ "$BAD" -eq 0 ] && echo "OK: technical content within 4 pages; page 5 holds only references / ethics / acknowledgements" || exit 1

#!/usr/bin/env bash
# SchemaAlign-ICU / Step 00: 物理层盘点
#
# 输入: $DATA_ROOT 下 6 个数据集的只读符号链接
# 输出: $OUT/00_file_inventory/
#         files.tsv        dataset \t relpath \t bytes \t n_data_rows \t n_cols
#         headers.tsv      dataset \t table \t col_index \t col_name
#         run.log
#
# 说明: 只统计解压后的 .csv（.csv.gz 为同源副本，跳过），避免重复计数。
set -uo pipefail

PROJ="/root/autodl-tmp/projects/SchemaAlign-ICU"
DATA="${PROJ}/data"
OUT="${PROJ}/outputs/00_file_inventory"
mkdir -p "$OUT"
: > "$OUT/files.tsv"
: > "$OUT/headers.tsv"

DATASETS="mimic-iv-3.1 mimic-iii-clinical-database-1.4 eicu_collaborative_research_database_2.0 mimic-iv-note-2.2 temporal-respiratory-support_1.1 MIMIC-sepsis"

echo "[00] start $(date -u +%FT%TZ)"

for ds in $DATASETS; do
  root="${DATA}/${ds}"
  [ -e "$root" ] || { echo "[00] MISSING $ds"; continue; }
  echo "[00] scanning $ds ..."
  # 收集候选 csv（排除 .git / __pycache__）
  find -L "$root" -type f -name '*.csv' \
       -not -path '*/.git/*' -not -path '*/__pycache__/*' 2>/dev/null \
  | sort > "$OUT/.list_${ds}.txt"

  while IFS= read -r f; do
    rel="${f#${root}/}"
    bytes=$(stat -c%s "$f")
    hdr=$(head -n 1 "$f")
    ncols=$(awk -F',' 'NR==1{print NF}' <<< "$hdr")
    # 数据行数 = 总行数 - 1（表头）
    total=$(wc -l < "$f")
    rows=$(( total > 0 ? total - 1 : 0 ))
    printf '%s\t%s\t%s\t%s\t%s\n' "$ds" "$rel" "$bytes" "$rows" "$ncols" >> "$OUT/files.tsv"
    # 表头逐列展开
    tbl=$(basename "$rel" .csv)
    awk -F',' -v ds="$ds" -v tbl="$tbl" 'NR==1{for(i=1;i<=NF;i++){g=$i; gsub(/^"|"$/,"",g); printf "%s\t%s\t%d\t%s\n", ds, tbl, i, g}}' <<< "$hdr" >> "$OUT/headers.tsv"
  done < "$OUT/.list_${ds}.txt"
  rm -f "$OUT/.list_${ds}.txt"
done

# parquet / 其它格式（MIMIC-sepsis 可能是 parquet）
find -L "${DATA}/MIMIC-sepsis" "${DATA}/temporal-respiratory-support_1.1" \
     -type f \( -name '*.parquet' -o -name '*.npz' -o -name '*.pkl' -o -name '*.json' -o -name '*.txt' -o -name '*.md' \) \
     -not -path '*/.git/*' 2>/dev/null | head -200 > "$OUT/other_files.txt"

echo "[00] done $(date -u +%FT%TZ)"
wc -l "$OUT/files.tsv" "$OUT/headers.tsv" "$OUT/other_files.txt"

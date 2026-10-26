# P0 凭据/实盘数据泄露 · 双远端 scrub 处置清单
**立案人**: 总管 · 2026-10-10 · 红线: AGENTS §4.1.7「数据不出本机」
**性质**: 事故已发生（泄露），本清单为根治方案，非新增。

---

## 一、泄露事实（一手证据，git 侧）

| 泄露物 | 载体 | 最早 commit | 已推远端 |
|--------|------|------------|---------|
| AGNES_API_KEY（sk-aHO…） | 硬编码在 dashboard/generate_dashboard.py + scripts/ai_analysis.py 的 env fallback + 多个 docs | `913d396d`(9-17) 起多个 | ✅ gitcode `6d27b7ab` + github `eeb3eab4` 远端 HEAD 均 `> aeb2036b`(09-28上云) |
| 实盘持仓 吉华 sh603980(cost 8.6) | data/holdings.json（.gitignore 白名单 !data/ 追踪） | `aeb2036b`(09-28) | ✅ 双远端均含 |

**根治结论**: key 自 9-17 起泄露多时（≥3 周），**历史 scrub 只能"删字面量"，不能让旧 key 失效**——唯一根治是 **rotate 密钥**（旧 key 作废，历史里留的旧 key 自动失效）。git scrub 是补充（降低旧 key 被从历史直接捞到的风险）。

## 二、已完成（本地止血，可逆）

1. ✅ `generate_dashboard.py` / `ai_analysis.py` 删硬编码 key fallback → 纯 `os.environ.get("AGNES_API_KEY")`（rotate 后设新 env 即通，**代码侧 A1 就绪**）
2. ✅ `.gitignore` 清空 7 件实盘白名单（L40-46）→ `data/` 回落默认 ignore
3. ✅ `git rm --cached data/holdings.json data/trade_log.json`（脱追踪，磁盘保留）
4. `tests/test_board_server.py` 的 `sk-aHO` 是**负向断言**（assertNotIn 测试"key 不在代码里"），是防线不是泄露，保留。

## 三、待执行（需老大拍板 + 老六远端配合，总管不动 git 历史/远端）

### A1 rotate 密钥（根治·最高优先）
- **谁做**: 老大在 AGNES 后台/API 换发新 key（总管无该权限）
- **代码侧**: 已就绪——rotate 后把新 key 写入 `~/.hermes/.env` 的 `AGNES_API_KEY`，重启 gateway，2 文件自动读到新 key
- **不 rotate 的后果**: 旧 key 永久有效，双远端历史里可直接复制，任何拿到 gitcode/github 仓库者都能调 AGNES API

### A2 git 双远端 scrub（补充·防旧 key 被历史直接捞）
**两条路径（推荐 ①，②风险更高）**:
- **① 务实路径（推荐）**: rotate 后旧 key 已失效 → **不做 history rewrite**，只在**新提交**里确认 key 已从工作树删除（已完成 A1），并给双远端打"已 rotate"标签。优点: 不 force-push、不改写 285 ahead 的共享历史、不动老六/老五协作线。
- **② 彻底路径（老六执行·需备份）**: `git filter-repo --replace-text` 把 `sk-aHO…` 全文替换为 `[REDACTED]`，重写 aeb2036b 之后所有 commit，双远端 force-push。风险: 改写共享历史 → 老六/老五本地需重新 clone；285 ahead 全量重写；需先 `git clone --mirror` 备份两远端。
- **实盘数据**: holdings/trade_log 现已脱追踪（A3），但历史里仍有吉华持仓。若走 ②，`filter-repo` 一并清 `sh603980`/`吉华` 载体的 data 文件历史版本；若走 ①，靠"数据已本地化 + 旧持仓已变动"降低风险。

### A3 已完成（见上），无需再动。

## 四、scrub 前必做（无论 ①/②）
- 备份双远端: `git clone --mirror gitcode:yzk19/zhuanqian.git` + `origin` 各一份到本机
- 确认无其他 profile/cron 仍引用旧 key 硬编码（全仓 `grep -rE 'sk-aHO' .` 只应命中 test_board_server.py 负向断言 + 本清单）

## 五、验收（SOUL#5 挂断言）
- rotate 后: 旧 key 调 AGNES API 返回 401（作废）
- A2 若走②: 双远端 `git log -S 'sk-aHO'` 为空 + 本地历史一致
- 全仓工作树 `grep -rE 'sk-aHO' .` 只剩 test_board_server.py 负向断言 + docs 里已脱敏引用
- `data/` 无任何实盘文件被追踪（`git ls-files data/` 排除白名单后为 audit/ 研究件，无 holdings/trade_log）

## 六、责任分界（SOUL 准则 2）
| 动作 | 谁 | 状态 |
|------|----|----|
| 删硬编码 + .gitignore 止血 + rm --cached | 总管 | ✅ 已完成 |
| rotate AGNES key | 老大（权限） | ⏳ 待执行 |
| 双远端 scrub（若走②） | 老六 + 老大授权 | ⏳ 待拍板 ①/② |
| 复盘归档 | 总管 | 本文件 |

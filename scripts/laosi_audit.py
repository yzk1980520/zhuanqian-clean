#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py dispatch
# -*- coding: utf-8 -*-
"""
老四自审Agent - 独立巡检脚本
执行时间: 每日20:00
报告输出: data/laosi_audit_report.json
飞书告警: P0/P1问题自动推送
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ======================================================================
# 任务契约块在位对账项（规则14读侧，t_330700bd 2026-10-21 老四；先例 M-3 派单审计）
# 判据真源: scripts/check_task_contract.py（C1-C5，本处不重实现）
# §3.4 登记: 消费方=老四20:00自审 周期=每日 失败路径=message_queue P1/P2
# ======================================================================
CONTRACT_CHECK_TIMEOUT_S = 60  # sqlite 只读轻操作；M-3 先例同档预算，超 → P2 降级跳过


def contract_violation_level(report):
    """窗口内违规>0 → 'P1'（含 R0 违规）/ 'P2'（其余）；None = 合规。"""
    if not report.get("violations"):
        return None
    return "P1" if report.get("r0_violations") else "P2"


def contract_queue_fingerprint(violations):
    """去重指纹：违规任务 id 排序拼接（与 09:30 cron 已入队的同组违规对账，防重复投递）。"""
    return "|".join(sorted(str(v.get("id", "")) for v in violations))


def contract_dedup_hit(queue_items, fp, now=None):
    """24h 内队列已存在同一违规集的 taskcontract_* 项 → True（跳过再入队）。

    09:30 QSP_TaskContractCheck 的条目无 dedup_fp 字段，用 content 内嵌 t_id 匹配；
    本对账项写的条目带 dedup_fp，先精确匹配。超 24h 视为已 drain/过期。
    """
    if now is None:
        now = time.time()
    my_tids = set(x for x in fp.split("|") if x)
    for it in queue_items or []:
        if not str(it.get("id", "")).startswith("taskcontract_"):
            continue
        try:
            ts = float(it.get("ts") or 0)
        except (TypeError, ValueError) as e:
            print(f"🔴 [laosi_audit.py:57] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 (TypeError, ValueError) → 兜底, 异常={e}", file=sys.stderr)
            continue
        if now - ts > 86400:
            continue
        if it.get("dedup_fp") == fp:
            return True
        content_tids = set(re.findall(r"t_[0-9a-f]{8}", str(it.get("content", ""))))
        if my_tids and content_tids and content_tids >= my_tids:
            return True
    return False


class LaosiAudit:
    def __init__(self):
        self.report = {
            'agent': 'laosi',
            'audit_time': None,
            'status': 'normal',
            'checks': {},
            'findings': [],
            'recommendations': []
        }
        
    def audit_holdings(self):
        """检查持仓状态"""
        holdings_path = ROOT / 'data' / 'holdings.json'
        if not holdings_path.exists():
            self.report['findings'].append({'level': 'P0', 'msg': 'holdings.json 不存在'})
            return False
        
        with open(holdings_path, encoding='utf-8') as f:
            h = json.load(f)
        
        pos = h.get('holdings', [])
        # 合规检查：全仓1只
        if len(pos) > 1:
            self.report['findings'].append({'level': 'P1', 'msg': f'持仓超限: {len(pos)}只'})
            self.report['status'] = 'warning'
        
        # 止损检查
        for p in pos:
            current = p.get('current_price', 0)
            stop = p.get('stop_loss', 0)
            symbol = p.get('symbol', '')
            if current > 0 and stop > 0:
                if current <= stop:
                    msg = f'{symbol} 止损触发: {current:.2f} <= {stop:.2f}'
                    self.report['findings'].append({'level': 'P0', 'msg': msg})
                    self.report['status'] = 'critical'
        
        self.report['checks']['holdings'] = 'pass'
        return True
    
    def audit_gate(self):
        """检查门禁状态"""
        review_path = ROOT / 'data' / 'review_status.json'
        if not review_path.exists():
            self.report['findings'].append({'level': 'P1', 'msg': 'review_status.json 不存在'})
            return False
        
        with open(review_path, encoding='utf-8') as f:
            r = json.load(f)
        
        approved = r.get('laowu_approved', False)
        if not approved:
            self.report['checks']['gate'] = 'frozen'
        else:
            self.report['checks']['gate'] = 'pass'
        
        return True
    
    def audit_factor_ic(self):
        """检查因子IC"""
        ic_path = ROOT / 'data' / 'factor_registry' / 'registry.json'
        if not ic_path.exists():
            self.report['checks']['factor_ic'] = 'na'
            return True
        
        with open(ic_path, encoding='utf-8') as f:
            ic = json.load(f)
        
        factors = ic.get('factors', {})
        invalid = []
        for name, data in factors.items():
            ic_mean = data.get('ic_mean')
            if ic_mean is not None and ic_mean < -0.03:
                invalid.append(f'{name}={ic_mean:.4f}')
        
        self.report['checks']['factor_ic'] = 'pass'
        if invalid:
            self.report['findings'].append({
                'level': 'P2', 
                'msg': f'IC反向因子: {len(invalid)}个 (阈值<-0.03)',
                'details': invalid[:5]
            })
        
        return True
    
    def audit_data_integrity(self):
        """检查数据完整性
        真源 = zhuanqian/data/history_daily（全项目唯一 K 线真源，15+ 处代码只读它）。
        旧判据指向 TSP tick-stock-panel-main/data/kline_daily（date= 分区）——
        该目录无任何任务/脚本灌数、长期为空，导致本检查永远假红(P0)；
        2026-10-25 老大指令下改回真源，杜绝"造假空目录把 P0 降 P1"的假绿路径。
        """
        kline_base = str(ROOT / 'data' / 'history_daily')
        if not os.path.isdir(kline_base):
            self.report['findings'].append({'level': 'P0', 'msg': f'history_daily 真源不存在: {kline_base}'})
            self.report['checks']['data_integrity'] = 'fail'
            return False

        files = [f for f in os.listdir(kline_base) if f.endswith('.json')]
        if len(files) < 8000:
            self.report['findings'].append({'level': 'P1', 'msg': f'history_daily 真源文件数异常: {len(files)} (< 8000)'})
            self.report['status'] = 'warning'

        self.report['checks']['data_integrity'] = 'pass'
        self.report['findings'].append({'level': 'INFO', 'msg': f'history_daily 真源文件数: {len(files)}'})
        return True
    
    def audit_signal(self):
        """检查今日信号"""
        signal_path = ROOT / 'data' / 'signal.json'
        if not signal_path.exists():
            self.report['checks']['signal'] = 'na'
            return True
        
        with open(signal_path, encoding='utf-8') as f:
            sig = json.load(f)
        
        pick = sig.get('top_pick', '')
        score = sig.get('score', 0)
        status = sig.get('status', '')
        
        self.report['checks']['signal'] = 'pass'
        self.report['findings'].append({
            'level': 'INFO',
            'msg': f'TOP1: {pick} 评分{score} 状态:{status}'
        })
        return True
    
    def audit_closedloop(self):
        """对账: 消费 daily_signal.closedloop 断言，漂移/缺失即报"""
        signal_path = ROOT / 'data' / 'daily_signal.json'
        if not signal_path.exists():
            self.report['findings'].append({'level': 'P1', 'msg': 'daily_signal.json 不存在，闭环完整率未记录'})
            self.report['checks']['closedloop'] = 'missing'
            return True
        try:
            with open(signal_path, encoding='utf-8') as f:
                sig = json.load(f)
            cl = sig.get('closedloop')
            if cl is None:
                self.report['findings'].append({'level': 'P1', 'msg': 'daily_signal.json 缺 closedloop 字段'})
                self.report['checks']['closedloop'] = 'missing'
                return True
            pct = cl.get('completeness_pct', 0)
            self.report['checks']['closedloop'] = f'{pct:.1f}%'
            if pct < 80:
                self.report['findings'].append({
                    'level': 'P1',
                    'msg': f'闭环完整率偏低: {pct}% ({cl.get("pass",0)}PASS/{cl.get("partial",0)}PARTIAL/{cl.get("fail",0)}FAIL)'
                })
            elif pct < 100:
                self.report['findings'].append({
                    'level': 'INFO',
                    'msg': f'闭环完整率: {pct}%（未达100%，有 {cl.get("partial",0)} 项 PARTIAL）'
                })
            else:
                self.report['findings'].append({
                    'level': 'INFO',
                    'msg': f'闭环完整率: {pct}% 全PASS'
                })
        except Exception as e:
            self.report['findings'].append({'level': 'P1', 'msg': f'闭环对账读取异常: {e}'})
            self.report['checks']['closedloop'] = 'error'
        return True

    # ==================================================================
    # 002-system-overview 规格/宪法对账项（T043, 2026-10-22；2026-10-24 升级动态解析）
    # 判据真源: .specify/memory/constitution.md（全部核心原则，动态检测）+ specs/002-system-overview/spec.md
    # 结果写入巡检报告 JSON: checks['spec_overview']
    # ==================================================================
    SPEC_OVERVIEW_MD = 'specs/002-system-overview/spec.md'
    CONSTITUTION_MD = '.specify/memory/constitution.md'
    # 宪法7原则 → 违宪条款特征 grep（命中任一 = 该原则违宪；口径=任务单"无违宪条款"）。
    # 2026-10-24 升级：动态检测宪法原则总数（当前11条），超出此 dict 的原则标 "no_pattern"。
    # 注：宪法 I 规定 spec 不得复述契约数值，故不要求 spec 出现"全仓1只/132日"等内容词，
    #     改为校验 spec 指向 risk_rules.py 真源（指针在位）。
    _SPEC_PRINCIPLE_VIOLATIONS = {
        'I_代码真源': [],  # 另行指针检查（见下方 check）
        'II_全仓1只': [r'全仓.{0,8}[2-9]只', r'多仓并行', r'分散持仓'],
        'III_TDD': [r'无测试可合入', r'免测试', r'跳过回归'],
        'IV_20转132': [r'快速版.{0,8}(直接|无需.{0,6})合入', r'20日.{0,6}(即可|足够)'],
        'V_数据不出本机': [r'数据可上传', r'允许.{0,4}外网传输', r'上传.{0,4}(云端|外网)'],
        'VI_评审不可绕过': [r'评审可绕过', r'无需评审', r'跳过评审', r'总管.{0,6}直接合入'],
        'VII_异常不吞噬': [r'静默吞异常', r'忽略.{0,4}异常'],  # 裸 except 语法另行逐行扫描
    }

    def audit_spec_overview(self):
        """002-system-overview 规格检查（T043）：
        ① spec.md / constitution.md 存在性；
        ② 宪法 I 指针检查：spec 须指向 risk_rules.py 真源（不得复述数值）；
        ③ 逐条 grep 宪法全部核心原则违宪条款特征（动态检测原则总数）+ 裸 except 语法（宪法 VII）；
        结果写 checks['spec_overview'] + findings，异常显式响铃（宪法 VII）。
        """
        spec_path = ROOT / self.SPEC_OVERVIEW_MD
        const_path = ROOT / self.CONSTITUTION_MD

        if not spec_path.exists():
            self.report['findings'].append(
                {'level': 'P1',
                 'msg': f'002-system-overview 规格缺失: {self.SPEC_OVERVIEW_MD}，系统认知地图断裂'})
            self.report['checks']['spec_overview'] = 'missing'
            self.report['status'] = 'warning'
            return False
        if not const_path.exists():
            self.report['findings'].append(
                {'level': 'P1',
                 'msg': f'宪法缺失: {self.CONSTITUTION_MD}，规格对账无判据真源'})
            self.report['checks']['spec_overview'] = 'missing_constitution'
            self.report['status'] = 'warning'
            return False

        try:
            spec_text = spec_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as e:
            self.report['findings'].append(
                {'level': 'P1', 'msg': f'002-system-overview 规格读取失败: {e}'})
            self.report['checks']['spec_overview'] = 'error'
            return True

        # 动态解析宪法原则总数（### I. / ### II. / ... / ### XI. 标题行）
        try:
            const_text = const_path.read_text(encoding='utf-8')
            _roman = r'[IVX]+'
            const_principle_names = re.findall(
                rf'^###\s+{_roman}\.\s+(.+?)(?:\s*[\((].*?[\])\)]?)?\s*$',
                const_text, re.MULTILINE)
            const_principle_count = len(const_principle_names)
        except (OSError, UnicodeDecodeError) as e:
            const_principle_count = len(self._SPEC_PRINCIPLE_VIOLATIONS)  # 降级到静态计数
            self.report['findings'].append(
                {'level': 'P2', 'msg': f'宪法读取失败，降级到静态原则数: {e}'})

        # ② 宪法 I 指针检查：spec 必须指向 risk_rules 真源
        has_pointer = 'risk_rules' in spec_text

        # ③ 逐条违宪条款 grep + 裸 except 逐行扫描
        principles = {}
        violations = []
        for name, pats in self._SPEC_PRINCIPLE_VIOLATIONS.items():
            hit = next((p for p in pats if re.search(p, spec_text)), None)
            principles[name] = 'pass' if hit is None else f'violation({hit})'
            if hit:
                violations.append(f'{name}: {hit}')
        # 动态补全：宪法中但无 grep 模式的原则标 no_pattern（不阻塞，仅透明）
        _static_count = len(self._SPEC_PRINCIPLE_VIOLATIONS)
        if const_principle_count > _static_count:
            for i in range(_static_count + 1, const_principle_count + 1):
                # 罗马数字映射（简单场景，I-XII 够用）
                _roman_map = {1:'I',2:'II',3:'III',4:'IV',5:'V',6:'VI',7:'VII',8:'VIII',9:'IX',10:'X',11:'XI',12:'XII'}
                key = f'{_roman_map.get(i,i)}_无模式'
                principles[key] = 'no_pattern'
        bare_except = [i for i, ln in enumerate(spec_text.splitlines(), 1)
                       if re.match(r'^\s*except\s*:', ln)]
        if bare_except:
            violations.append(f'VII_异常不吞噬: bare_except@L{bare_except[0]}')
        if not has_pointer:
            principles['I_代码真源'] = 'no_true_source_pointer'
            violations.append('I_代码真源: spec 未指向 risk_rules.py 真源')
        else:
            principles['I_代码真源'] = 'pass'

        result = 'pass' if not violations else 'fail'
        self.report['checks']['spec_overview'] = {
            'spec': self.SPEC_OVERVIEW_MD,
            'constitution': self.CONSTITUTION_MD,
            'principles': principles,
            'violations': violations,
            'result': result,
        }
        if violations:
            self.report['findings'].append({
                'level': 'P1',
                'msg': f'002-spec 违宪条款命中: {violations}'})
            self.report['status'] = 'warning'
        else:
            self.report['findings'].append({
                'level': 'INFO',
                'msg': f'002-spec 宪法{const_principle_count}原则逐条 grep 无违宪条款（{const_principle_count}/{const_principle_count} pass，真源指针在位）'})
        return True

    def audit_task_contract(self):
        """任务契约块在位对账（规则14读侧消费，§3.4 已登记；先例 M-3 派单审计同模式）。

        调 scripts/check_task_contract.py --json --no-snapshot（判据真源 C1-C5，不重实现）:
          rc=0 合规 → checks['task_contract']='pass'
          rc=1 违规>0 → finding P1（含 R0 违规）/ P2（其余）+ 写 data/message_queue.json
              （规则11 唯一出口 → QSP_MsgDrain 投递；24h 去重守卫防与 09:30 cron 重复入队）
          rc=2 看板库不可达 → P1 响亮 finding（未上线=未闭环，M-4 同口径）
          60s 预算超 → P2 降级跳过，不阻塞主流程（M-3 先例）
        注: 20:00 消费侧不启用 --alert（该出口归 09:30 QSP_TaskContractCheck 独占），
            入队决策点唯一在本对账项。
        """
        script = ROOT / 'scripts' / 'check_task_contract.py'
        if not script.exists():
            self.report['findings'].append(
                {'level': 'P1', 'msg': '契约块对账: check_task_contract.py 缺失，规则14读侧断裂'})
            self.report['checks']['task_contract'] = 'missing'
            self.report['status'] = 'warning'
            return False

        try:
            r = subprocess.run(
                [sys.executable, str(script), '--json', '--no-snapshot'],
                cwd=str(ROOT), capture_output=True, text=True,
                encoding='utf-8', timeout=CONTRACT_CHECK_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.report['findings'].append({
                'level': 'P2',
                'msg': (f'契约块对账: 超时跳过（P2降级，{CONTRACT_CHECK_TIMEOUT_S}s 预算耗尽），'
                        '不阻塞主流程')})
            self.report['checks']['task_contract'] = 'timeout'
            return True

        try:
            rep = json.loads((r.stdout or '').strip() or '{}')
        except Exception as e:
            self.report['findings'].append(
                {'level': 'P1', 'msg': f'契约块对账: JSON 解析失败: {e}'})
            self.report['checks']['task_contract'] = 'error'
            self.report['status'] = 'warning'
            return True

        if r.returncode == 2 or not rep.get('db'):
            self.report['findings'].append({
                'level': 'P1',
                'msg': (f'契约块对账: 看板库不可达（rc={r.returncode}）— 审计链断裂'
                        '（未上线=未闭环）')})
            self.report['checks']['task_contract'] = 'db_unreachable'
            self.report['status'] = 'warning'
            return True

        level = contract_violation_level(rep)
        if level is None:
            self.report['checks']['task_contract'] = 'pass'
            self.report['findings'].append({
                'level': 'INFO',
                'msg': (f"契约块对账: 窗口内 {rep.get('in_window', 0)} 单全部合规"
                        f"（开放在途 {rep.get('checked_open', 0)} 单，判据规则14 C1-C5）")})
            return True

        violations = rep.get('violations', [])
        parts = []
        for v in violations[:8]:
            rid = "R0" if v.get("r0") else "R1/R2"
            missing = "/".join(v.get("missing", []))
            parts.append("%s(%s)缺[%s]" % (v.get("id"), rid, missing))
        ids_preview = "; ".join(parts)
        self.report['checks']['task_contract'] = f"fail({len(violations)})"
        self.report['findings'].append({
            'level': level,
            'msg': (f"契约块对账: {len(violations)} 个在途单缺契约项"
                    f"（R0违规 {rep.get('r0_violations', 0)}）: {ids_preview}"),
            'details': violations[:8],
        })
        if level == 'P1':
            self.report['status'] = 'warning'

        # 写 data/message_queue.json（规则11 唯一出口 → QSP_MsgDrain 投递；24h 去重守卫）
        try:
            from core.pipeline.atomic_json import atomic_dump, atomic_load
            q = str(ROOT / 'data' / 'message_queue.json')
            items = atomic_load(q, []) or []
            fp = contract_queue_fingerprint(violations)
            if contract_dedup_hit(items, fp):
                self.report['findings'].append({
                    'level': 'INFO',
                    'msg': '契约块对账: 同日违规已在队（24h去重守卫命中），不再重复入队'})
            else:
                now = time.time()
                items.append({
                    'id': f"taskcontract_{level.lower()}_{int(now)}",
                    'content': (f"⚠️ [任务契约审计-20:00对账-{level}] {len(violations)} 个在途单缺契约项: "
                                f"{ids_preview}（判据: docs/多Agent任务契约与自愈规则-元宝对照-20261020.md §二；"
                                f"与 09:30 QSP_TaskContractCheck 同日去重）"),
                    'platform': 'feishu',
                    'ts': now,
                    'dedup_fp': fp,
                    'origin': 'laosi_audit_20:00',
                })
                atomic_dump(items, q)
                self.report['findings'].append({
                    'level': 'INFO',
                    'msg': f'契约块对账: 已入队 {level} ×1 → data/message_queue.json（QSP_MsgDrain 投递）'})
        except Exception as e:
            self.report['findings'].append(
                {'level': 'P1', 'msg': f'契约块对账: 写 message_queue 失败: {e}'})
        return True

    def run(self):
        """执行完整巡检"""
        self.report['audit_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 执行所有检查
        self.audit_holdings()
        self.audit_gate()
        self.audit_factor_ic()
        self.audit_data_integrity()
        self.audit_signal()
        self.audit_closedloop()
        self.audit_spec_overview()
        self.audit_task_contract()
        
        # 生成报告
        report_path = ROOT / 'data' / 'laosi_audit_report.json'
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(self.report, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 老四自审完成: {self.report['audit_time']}")
        print(f"   状态: {self.report['status']}")
        print(f"   检查项: {len(self.report['checks'])}")
        print(f"   发现: {len(self.report['findings'])} 条")
        
        # 输出P0/P1告警
        alerts = [f for f in self.report['findings'] if f.get('level') in ['P0', 'P1']]
        if alerts:
            print(f"\n⚠️ P0/P1告警:")
            for a in alerts:
                print(f"   [{a['level']}] {a['msg']}")
        
        return self.report

if __name__ == '__main__':
    audit = LaosiAudit()
    audit.run()

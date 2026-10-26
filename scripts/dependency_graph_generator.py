#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块依赖关系图生成器 — ast.parse 静态分析 (US3)

遍历指定目录下的所有 .py 文件，提取 import/from-import 语句，
生成 DependencyGraph JSON 写入 data/system/dependency_graph.json。

FR-008: 覆盖 >= 95% 导入关系。
宪法 VII: 无裸 except:，显式异常类型。
"""
import ast
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT = Path(__file__).resolve().parent.parent
DATA_SYSTEM = PROJECT / "data" / "system"
OUTPUT_PATH = DATA_SYSTEM / "dependency_graph.json"

# 已知动态导入模式（无法通过 ast.parse 捕获）
DYNAMIC_IMPORT_PATTERNS = [
    # (source_module_pattern, target_module_pattern, reason)
]


def extract_imports(file_path: Path) -> list:
    """从单文件提取所有 import 语句。"""
    edges = []
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        print(f"  [WARN] SyntaxError in {file_path}: {exc}", file=sys.stderr)
        return edges
    except UnicodeDecodeError as exc:
        print(f"  [WARN] UnicodeDecodeError in {file_path}: {exc}", file=sys.stderr)
        return edges
    except OSError as exc:
        print(f"  [WARN] OSError reading {file_path}: {exc}", file=sys.stderr)
        return edges

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.name.split(".")[0]  # 取顶层模块
                edges.append({
                    "source": str(file_path.relative_to(PROJECT)),
                    "target": f"{target}.py",
                    "import_type": "direct",
                    "line_number": node.lineno,
                    "symbol": alias.asname or alias.name,
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0:  # absolute import
                target_base = module.split(".")[0]
                target = f"{target_base}.py"
            else:  # relative import
                # 尝试解析相对路径
                parent = file_path.parent
                for _ in range(node.level - 1):
                    parent = parent.parent
                # 简化处理：记录为 direct
                target = f"{module.split('.')[0]}.py" if module else "unknown.py"
            edges.append({
                "source": str(file_path.relative_to(PROJECT)),
                "target": target,
                "import_type": "from_import",
                "line_number": node.lineno,
                "symbol": ", ".join(a.name for a in node.names) if node.names else "*",
            })
    return edges


def detect_dynamic_imports(file_path: Path) -> list:
    """检测动态导入（ast.parse 无法捕获）。"""
    annotations = []
    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        return annotations

    # 检测 __import__()
    import re
    for match in re.finditer(r"__import__\(['\"]([^'\"]+)['\"]\)", source):
        target_module = match.group(1).split(".")[0]
        annotations.append({
            "source": str(file_path.relative_to(PROJECT)),
            "target": f"{target_module}.py",
            "reason": f"dynamic import via __import__ at line {source[:match.start()].count(chr(10)) + 1}",
        })

    # 检测 importlib.import_module
    for match in re.finditer(r"importlib\.import_module\(['\"]([^'\"]+)['\"]\)", source):
        target_module = match.group(1).split(".")[0]
        annotations.append({
            "source": str(file_path.relative_to(PROJECT)),
            "target": f"{target_module}.py",
            "reason": f"dynamic import via importlib.import_module",
        })

    return annotations


def generate_dependency_graph(
    root_dir: Path,
    scan_dirs: list[str] | None = None,
) -> dict:
    """生成全量依赖关系图。"""
    if scan_dirs is None:
        scan_dirs = ["scripts", "tests", "dashboards"]

    all_edges = []
    all_annotations = []
    all_files = set()

    for scan_dir in scan_dirs:
        dir_path = root_dir / scan_dir
        if not dir_path.exists():
            continue
        for py_file in sorted(dir_path.glob("*.py")):
            all_files.add(str(py_file.relative_to(root_dir)))
            edges = extract_imports(py_file)
            all_edges.extend(edges)
            dyn = detect_dynamic_imports(py_file)
            all_annotations.extend(dyn)

    # 去重
    seen = set()
    unique_edges = []
    for edge in all_edges:
        key = (edge["source"], edge["target"], edge["line_number"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(edge)

    # 找孤立模块（无任何 import 关系的目标）
    imported_targets = {e["target"] for e in unique_edges}
    orphan_modules = sorted([f for f in all_files if f not in imported_targets and "test_" not in f])

    total_edges = len(unique_edges) + len(all_annotations)

    graph = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_edges": total_edges,
        "edges": unique_edges,
        "orphan_modules": orphan_modules,
        "manual_annotations": all_annotations,
    }
    return graph


def main() -> int:
    """入口：生成依赖图并写入文件。

    支持 --incremental <file1> <file2> ... 模式：
      仅对指定文件重新 ast.parse，替换其 edges，合并到既有 dependency_graph.json。
      未列出的文件保持既有 edges 不变（用于 pre-commit 钩子，增量 ≤ 5s）。
    """
    import argparse
    parser = argparse.ArgumentParser(description="模块依赖图生成器")
    parser.add_argument("--incremental", nargs="*", default=None,
                        metavar="FILE", help="增量模式：仅重新解析这些文件（路径相对于仓库根）")
    args = parser.parse_args()

    start = __import__("time").time()
    try:
        DATA_SYSTEM.mkdir(parents=True, exist_ok=True)

        if args.incremental is not None:
            # 增量模式：解析指定文件，合并到既有图
            existing = {}
            if OUTPUT_PATH.exists():
                try:
                    existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    print(f"  [WARN] 既有 dependency_graph.json 读取失败，全量重建: {exc}", file=sys.stderr)
                    existing = {}
            existing_edges = existing.get("edges", [])
            existing_ann = existing.get("manual_annotations", [])

            # 确定要重新解析的文件
            staged_paths = []
            for rel in args.incremental:
                p = PROJECT / rel
                if p.suffix != ".py" or not p.exists():
                    continue
                staged_paths.append(p)

            if not staged_paths:
                elapsed = int((__import__("time").time() - start) * 1000)
                print(f"  [incremental] 无可解析 .py 文件，跳过 ({elapsed}ms)")
                return 0

            # 移除这些文件 source 的旧 edges
            staged_rels = {str(p.relative_to(PROJECT)) for p in staged_paths}
            filtered_edges = [e for e in existing_edges if e.get("source") not in staged_rels]
            filtered_ann = [a for a in existing_ann if a.get("source") not in staged_rels]

            # 重新解析 staged 文件
            new_edges = []
            new_ann = []
            for p in staged_paths:
                new_edges.extend(extract_imports(p))
                new_ann.extend(detect_dynamic_imports(p))

            merged_edges = filtered_edges + new_edges
            merged_ann = filtered_ann + new_ann

            # 去重
            seen = set()
            unique_edges = []
            for edge in merged_edges:
                key = (edge["source"], edge["target"], edge["line_number"])
                if key not in seen:
                    seen.add(key)
                    unique_edges.append(edge)

            graph = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_edges": len(unique_edges) + len(merged_ann),
                "edges": unique_edges,
                "orphan_modules": existing.get("orphan_modules", []),
                "manual_annotations": merged_ann,
            }
            output = json.dumps(graph, ensure_ascii=False, indent=2)
            OUTPUT_PATH.write_text(output, encoding="utf-8")
            elapsed = int((__import__("time").time() - start) * 1000)
            print(f"  [incremental] {len(staged_paths)} files → total_edges={graph['total_edges']} ({elapsed}ms)")
            return 0
        else:
            # 全量模式（原有逻辑）
            graph = generate_dependency_graph(PROJECT)
            output = json.dumps(graph, ensure_ascii=False, indent=2)
            OUTPUT_PATH.write_text(output, encoding="utf-8")
            elapsed = int((__import__("time").time() - start) * 1000)
            print(f"Dependency graph written: {OUTPUT_PATH}")
            print(f"  total_edges={graph['total_edges']}, edges={len(graph['edges'])}, "
                  f"annotations={len(graph['manual_annotations'])}, "
                  f"orphan_modules={len(graph['orphan_modules'])}")
            print(f"  generated in {elapsed}ms")
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

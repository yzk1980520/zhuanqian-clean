#!/usr/bin/env python3
"""
TDD: 文件修改校验器 - 测试先行

Seam（测试边界）:
  - validate_file_changes(file_path, expected_hashes) -> dict
    输入：文件路径 + 预期哈希值
    输出：{'valid': bool, 'mismatches': list, 'errors': list}
  
  - compute_file_hash(file_path) -> str
    输入：文件路径
    输出：SHA256哈希字符串

  - check_protocol_integrity() -> dict
    输入：无
    输出：{'status': str, 'details': dict}

[t_laosan_c1_test_alignment] 2026-10-24 (裁决日 2026-10-23):
10/23 大归档后, 被测模块 scripts/file_change_validator.py 已归档
(archive/scripts-20261023/file_change_validator.py), 测试侧对齐归档后真源:
  - compute_file_hash (SHA256 文件哈希原语) → 重定向到活跃等价
    scripts/record_gate_fingerprint.sha256_of (门禁产物指纹台账, 同原语同口径)
  - validate_file_changes / check_protocol_integrity → 无活跃等价 API,
    原 8 测试删除挂理由:
      * 文件完整性校验现由 scripts/record_gate_fingerprint.py 指纹台账
        (sha256+关键值+来源链, state/gate_fingerprints.jsonl) 承担;
      * 协议挂载检查现由 scripts/check_protocol_mount.py 承担;
      * 走前指纹校验现由 scripts/verify_walk_forward_fingerprint.py 承担。
"""

import pytest
import hashlib
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta


class TestComputeFileHash:
    """测试文件SHA256哈希原语 (对齐活跃等价: scripts/record_gate_fingerprint.sha256_of)

    [t_laosan_c1_test_alignment] 原 import scripts.file_change_validator.compute_file_hash
    已随 2026-10-23 归档下线 (archive/scripts-20261023/file_change_validator.py);
    哈希原语活跃真源 = scripts/record_gate_fingerprint.py sha256_of (64位hex, 分块读)。
    """

    def test_compute_hash_returns_string(self):
        """哈希值应为字符串"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("test content")
            temp_path = f.name

        try:
            from scripts.record_gate_fingerprint import sha256_of
            result = sha256_of(temp_path)
            assert isinstance(result, str)
            assert len(result) == 64  # SHA256长度
        finally:
            os.unlink(temp_path)

    def test_compute_hash_deterministic(self):
        """相同内容应产生相同哈希"""
        content = "consistent content"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f1:
            f1.write(content)
            path1 = f1.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f2:
            f2.write(content)
            path2 = f2.name

        try:
            from scripts.record_gate_fingerprint import sha256_of
            hash1 = sha256_of(path1)
            hash2 = sha256_of(path2)
            assert hash1 == hash2
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_compute_hash_different_content(self):
        """不同内容应产生不同哈希"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f1:
            f1.write("content A")
            path1 = f1.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f2:
            f2.write("content B")
            path2 = f2.name

        try:
            from scripts.record_gate_fingerprint import sha256_of
            hash1 = sha256_of(path1)
            hash2 = sha256_of(path2)
            assert hash1 != hash2
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_compute_hash_empty_file(self):
        """空文件应能计算哈希"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            pass  # 空文件
            path = f.name

        try:
            from scripts.record_gate_fingerprint import sha256_of
            result = sha256_of(path)
            assert isinstance(result, str)
            assert len(result) == 64
        finally:
            os.unlink(path)


class TestValidateFileChanges:
    """文件修改校验 (validate_file_changes) 测试

    [t_laosan_c1_test_alignment] 原 5 测试 (test_valid_file_returns_valid_true /
    test_modified_file_returns_valid_false / test_missing_file_returns_error /
    test_multiple_files_all_valid / test_multiple_files_one_modified, 均 import
    scripts.file_change_validator) 已删除:
    归档源 archive/scripts-20261023/file_change_validator.py (2026-10-23 裁决),
    validate_file_changes API 无活跃等价; 文件完整性校验现由
    scripts/record_gate_fingerprint.py 指纹台账 (sha256+关键值+来源链) 承担,
    哈希原语覆盖见 TestComputeFileHash (本文件)。
    """
    pass


class TestCheckProtocolIntegrity:
    """协议完整性检查 (check_protocol_integrity) 测试

    [t_laosan_c1_test_alignment] 原 3 测试 (test_returns_status_dict /
    test_status_is_string / test_details_is_dict, 均 import
    scripts.file_change_validator) 已删除:
    归档源 archive/scripts-20261023/file_change_validator.py (2026-10-23 裁决),
    check_protocol_integrity API 无活跃等价; 协议挂载检查现由
    scripts/check_protocol_mount.py 承担 (走前指纹由 scripts/verify_walk_forward_fingerprint.py)。
    """
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_manager.py - 本地语义记忆管理模块 v1.0.0

功能:
- add_experience: 添加经验教训（自动编码存储）
- search_similar: 语义检索相似经验（Top-K）
- get_all_memories: 获取所有历史记忆
- clear_memories: 清理过期记忆
- export_to_json: 导出备份
- import_from_json: 导入恢复

架构:
- 向量存储: ChromaDB（本地文件，无外泄风险）
- Embedding: 内置模型（384维，离线可用）
- 持久化: C:/Users/WIN10/.mem0_chroma/

作者: 总管（Hermes）
时间: 2026-09-14
版本: v1.0.0
"""
import os
import json
import uuid
import glob
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

import chromadb
from chromadb.config import Settings


@dataclass
class MemoryRecord:
    """记忆记录数据结构"""
    id: str
    content: str
    category: str  # experience/decision/failure/skill
    metadata: Dict
    created_at: str
    embedding_id: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def to_text(self) -> str:
        """转换为文本（用于向量编码）"""
        text = self.content
        if self.metadata.get('context'):
            text += f"\n上下文: {self.metadata['context']}"
        if self.metadata.get('outcome'):
            text += f"\n结果: {self.metadata['outcome']}"
        return text


class MemoryManager:
    """本地语义记忆管理器"""
    
    def __init__(self, persist_path: str = None):
        """
        初始化记忆管理器
        
        Args:
            persist_path: ChromaDB持久化路径（默认用户目录）
        """
        # 默认路径
        if persist_path is None:
            persist_path = Path.home() / '.mem0_chroma'
        
        self.persist_path = str(Path(persist_path).resolve())
        self.collection_name = 'zhuanqian_memories'
        
        # 初始化ChromaDB客户端（本地模式）
        self.client = chromadb.PersistentClient(
            path=self.persist_path,
            settings=Settings(anonymized_telemetry=False)
        )
        
        # 初始化embedding函数（使用内置模型）
        self.ef = chromadb.utils.embedding_functions.DefaultEmbeddingFunction()
        
        # 获取或创建collection
        self.collection = self._get_or_create_collection()
        
        # 元数据存储（JSON文件）
        self.metadata_path = Path(self.persist_path) / 'metadata.json'
        self._load_metadata()
    
    def _get_or_create_collection(self) -> chromadb.Collection:
        """获取或创建ChromaDB collection"""
        try:
            return self.client.get_collection(
                name=self.collection_name,
                embedding_function=self.ef
            )
        except Exception:
            return self.client.create_collection(
                name=self.collection_name,
                embedding_function=self.ef,
                metadata={"hnsw:space": "cosine"}
            )
    
    def _load_metadata(self):
        """加载元数据"""
        if self.metadata_path.exists():
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
        else:
            self.metadata = {
                'total_memories': 0,
                'categories': {},
                'last_updated': None,
                'stats': {}
            }
    
    def _save_metadata(self):
        """保存元数据"""
        self.metadata['total_memories'] = self.collection.count()
        self.metadata['last_updated'] = datetime.now().isoformat()
        
        # 统计各类别数量
        if self.collection.count() > 0:
            all_records = self.collection.get()
            categories = {}
            for meta in all_records['metadatas']:
                cat = meta.get('category', 'unknown')
                categories[cat] = categories.get(cat, 0) + 1
            self.metadata['categories'] = categories
        
        with open(self.metadata_path, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)
    
    def add_experience(
        self,
        content: str,
        category: str = 'experience',
        context: str = None,
        outcome: str = None,
        tags: List[str] = None
    ) -> MemoryRecord:
        """
        添加经验教训
        
        Args:
            content: 经验内容（核心文本）
            category: 类别（experience/decision/failure/skill）
            context: 上下文信息
            outcome: 结果反馈
            tags: 标签列表
            
        Returns:
            MemoryRecord: 创建的记忆记录
        """
        # 生成唯一ID
        record_id = str(uuid.uuid4())[:8]
        
        # 构建元数据
        metadata = {
            'category': category,
            'tags': json.dumps(tags or [], ensure_ascii=False),
            'context': context or '',
            'outcome': outcome or ''
        }
        
        # 转换为文本用于向量编码
        text = content
        if context:
            text += f"\n上下文: {context}"
        if outcome:
            text += f"\n结果: {outcome}"
        
        # 存储到ChromaDB
        self.collection.add(
            documents=[text],
            metadatas=[metadata],
            ids=[record_id]
        )
        
        # 创建记录对象
        record = MemoryRecord(
            id=record_id,
            content=content,
            category=category,
            metadata={
                'context': context,
                'outcome': outcome,
                'tags': tags or [],
                'created_at': datetime.now().isoformat()
            },
            created_at=datetime.now().isoformat()
        )
        
        # 更新元数据
        self._save_metadata()
        
        return record
    
    def search_similar(
        self,
        query: str,
        top_k: int = 5,
        category: str = None,
        min_score: float = 0.7
    ) -> List[Dict]:
        """
        语义检索相似经验
        
        Args:
            query: 查询文本
            top_k: 返回结果数量
            category: 过滤类别（可选）
            min_score: 最低相似度阈值（0-1）
            
        Returns:
            List[Dict]: 相似经验列表
        """
        if self.collection.count() == 0:
            return []
        
        # 执行查询
        results = self.collection.query(
            query_texts=[query],
            n_results=min(top_k, self.collection.count()),
            where={'category': category} if category else None,
            include=['documents', 'metadatas', 'distances']
        )
        
        # 解析结果
        experiences = []
        if results['ids'] and results['ids'][0]:
            for i, doc_id in enumerate(results['ids'][0]):
                # 计算相似度分数（ChromaDB返回的是距离，转换为相似度）
                distance = results['distances'][0][i]
                similarity = 1 - (distance / 2)  # cosine distance -> similarity
                
                if similarity >= min_score:
                    metadata = results['metadatas'][0][i]
                    experiences.append({
                        'id': doc_id,
                        'content': results['documents'][0][i],
                        'similarity': round(similarity, 3),
                        'category': metadata.get('category', 'unknown'),
                        'tags': json.loads(metadata.get('tags', '[]')),
                        'context': metadata.get('context', ''),
                        'outcome': metadata.get('outcome', '')
                    })
        
        return experiences
    
    def get_all_memories(self, category: str = None) -> List[MemoryRecord]:
        """
        获取所有记忆记录
        
        Args:
            category: 过滤类别（可选）
            
        Returns:
            List[MemoryRecord]: 所有记忆记录
        """
        if self.collection.count() == 0:
            return []
        
        where = {'category': category} if category else None
        results = self.collection.get(where=where)
        
        memories = []
        for i, doc_id in enumerate(results['ids']):
            metadata = results['metadatas'][i]
            memories.append(MemoryRecord(
                id=doc_id,
                content=results['documents'][i],
                category=metadata.get('category', 'unknown'),
                metadata={
                    'context': metadata.get('context', ''),
                    'outcome': metadata.get('outcome', ''),
                    'tags': json.loads(metadata.get('tags', '[]'))
                },
                created_at=metadata.get('created_at', '')
            ))
        
        return memories
    
    def clear_memories(self, category: str = None, older_than_days: int = None):
        """
        清理记忆记录
        
        Args:
            category: 清理指定类别
            older_than_days: 清理超过N天的记录
        """
        if self.collection.count() == 0:
            return
        
        # 构建删除条件
        where = {}
        if category:
            where['category'] = category
        
        # 执行清理（简化版，实际可能需要更复杂的逻辑）
        if category:
            # 删除指定类别的所有记录
            self.collection.delete(where={'category': category})
        else:
            # 清空所有记录
            self.client.delete_collection(self.collection_name)
            self.collection = self._get_or_create_collection()
        
        # 更新元数据
        self._save_metadata()
    
    def get_stats(self) -> Dict:
        """获取记忆库统计信息"""
        return {
            'total_memories': self.collection.count(),
            'categories': self.metadata.get('categories', {}),
            'last_updated': self.metadata.get('last_updated'),
            'storage_path': self.persist_path
        }
    
    def export_to_json(self, output_path: str = None) -> str:
        """导出记忆库为JSON文件"""
        if output_path is None:
            output_path = Path.home() / f'memories_{datetime.now().strftime("%Y%m%d")}.json'
        
        memories = self.get_all_memories()
        data = {
            'export_time': datetime.now().isoformat(),
            'total_count': len(memories),
            'memories': [m.to_dict() for m in memories]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return str(output_path)
    
    def import_from_json(self, input_path: str) -> int:
        """从JSON文件导入记忆"""
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        count = 0
        for mem in data.get('memories', []):
            self.add_experience(
                content=mem['content'],
                category=mem['category'],
                context=mem['metadata'].get('context'),
                outcome=mem['metadata'].get('outcome'),
                tags=mem['metadata'].get('tags')
            )
            count += 1
        
        return count


# 全局单例
_memory_manager = None

def get_memory_manager() -> MemoryManager:
    """获取全局记忆管理器实例"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


def add_experience(content: str, **kwargs) -> MemoryRecord:
    """便捷函数：添加经验"""
    return get_memory_manager().add_experience(content, **kwargs)


def search_experiences(query: str, **kwargs) -> List[Dict]:
    """便捷函数：搜索经验"""
    return get_memory_manager().search_similar(query, **kwargs)


if __name__ == '__main__':
    # 测试代码
    
    # 初始化
    mgr = MemoryManager()
    
    # 测试添加
    test_cases = [
        {
            'content': '环境门判断失误：误判门关导致错过选股机会',
            'category': 'failure',
            'context': '环境门MA250计算错误',
            'outcome': '损失当日选股机会，次日修正'
        },
        {
            'content': '因子IC翻转检测及时：alpha13/alpha16_fix死亡，chg5/chg10崛起',
            'category': 'experience',
            'context': '2026年市场风格切换',
            'outcome': '成功切换至动量因子策略'
        },
        {
            'content': 'skill库大规模corruption修复：正则替换累积损坏',
            'category': 'experience',
            'context': 'hermes-skill-format-pitfalls维护',
            'outcome': '恢复完整引用关系'
        }
    ]
    
    for tc in test_cases:
        record = mgr.add_experience(**tc)
        print(f"   ✅ 添加: {record.id} - {tc['category']}")
    
    # 测试检索
    queries = [
        '环境门判断失误',
        '因子IC翻转',
        '技能库修复'
    ]
    
    for query in queries:
        results = mgr.search_similar(query, top_k=2)
        print(f"\n   查询: '{query}'")
        for r in results:
            print(f"      - 相似度{r['similarity']:.3f}: {r['content'][:50]}...")
    
    # 测试统计
    stats = mgr.get_stats()
    print(f"   总记录数: {stats['total_memories']}")
    print(f"   类别分布: {stats['categories']}")
    print(f"   存储路径: {stats['storage_path']}")
    
    # 测试导出
    export_path = mgr.export_to_json()
    print(f"   ✅ 导出成功: {export_path}")
    
    # 测试导入
    import_count = mgr.import_from_json(export_path)
    print(f"   ✅ 导入成功: {import_count}条记录")
    

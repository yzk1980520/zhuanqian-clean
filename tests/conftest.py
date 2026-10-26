"""Pytest fixtures for laya tests."""
import os
import pytest


@pytest.fixture(scope="session")
def model_path():
    """获取本地模型路径"""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models", "laya-typed-decisions"
    )


@pytest.fixture
def agent(model_path):
    """加载测试用的 Agent"""
    import sys
    os.environ['USE_TF'] = '0'
    
    if not os.path.exists(model_path):
        pytest.skip("Local model not found")
    
    from laya.agent import Agent
    return Agent(model_path)

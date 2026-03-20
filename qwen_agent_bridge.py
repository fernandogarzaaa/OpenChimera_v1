"""
CHIMERA + Qwen-Agent Integration Module

This module bridges CHIMERA with Qwen-Agent's multi-agent capabilities.
Allows CHIMERA to use Qwen-Agent's:
- ReAct Chat agents
- Function calling
- Group chat orchestration
- Browser assistant
- Code interpreter
"""

import os
import sys
from typing import Any, Optional

# Add Qwen-Agent to path
QWEN_AGENT_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'Qwen-Agent', 'qwen_agent')
if os.path.exists(QWEN_AGENT_PATH):
    sys.path.insert(0, os.path.dirname(QWEN_AGENT_PATH))

class QwenAgentBridge:
    """
    Bridge between CHIMERA and Qwen-Agent
    
    Uses CHIMERA's local LLM as the backend for Qwen-Agent
    """
    
    def __init__(self, chimera_url: str = "http://localhost:7861"):
        self.chimera_url = chimera_url
        self.qwen_available = self._check_qwen_agent()
        
    def _check_qwen_agent(self) -> bool:
        """Check if Qwen-Agent is available"""
        qwen_path = os.path.join(os.path.dirname(__file__), '..', '..', 'Qwen-Agent')
        return os.path.exists(qwen_path)
    
    def create_react_agent(self, tools: list = None):
        """
        Create a ReAct (Reasoning + Acting) agent
        
        ReAct agents can:
        - Think step by step
        - Use tools/functions
        - Learn from feedback
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not found"}
            
        try:
            from qwen_agent.agents import ReActChat
            from qwen_agent.tools import BaseTool
            
            # Create agent with CHIMERA as backend
            agent = ReActChat(
                llm={
                    'model': 'qwen-turbo',
                    'api_key': 'dummy',  # Will be overridden
                    'base_url': f'{self.chimera_url}/v1'
                },
                tools=tools or []
            )
            return agent
        except Exception as e:
            return {"error": str(e)}
    
    def create_function_agent(self, functions: list = None):
        """
        Create a function-calling agent
        
        Can call external APIs and functions
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not found"}
            
        try:
            from qwen_agent.agents import FnCallAgent
            
            agent = FnCallAgent(
                llm={
                    'model': 'qwen-turbo', 
                    'base_url': f'{self.chimera_url}/v1'
                },
                function_list=functions or []
            )
            return agent
        except Exception as e:
            return {"error": str(e)}
    
    def create_group_chat(self, agents: list = None):
        """
        Create a multi-agent group chat
        
        Multiple agents collaborate on tasks
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not found"}
            
        try:
            from qwen_agent.agents import GroupChat
            
            group = GroupChat(
                llm={
                    'model': 'qwen-turbo',
                    'base_url': f'{self.chimera_url}/v1'
                },
                agents=agents or []
            )
            return group
        except Exception as e:
            return {"error": str(e)}
    
    def run_browser_assistant(self, url: str = None):
        """
        Create a browser assistant agent
        
        Can browse web, click, type, etc.
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not found"}
            
        try:
            from qwen_agent.agents import BrowserAssistant
            
            assistant = BrowserAssistant(
                llm={
                    'model': 'qwen-turbo',
                    'base_url': f'{self.chimera_url}/v1'
                }
            )
            return assistant
        except Exception as e:
            return {"error": str(e)}
    
    def run_code_interpreter(self):
        """
        Create a code interpreter agent
        
        Can execute Python code safely
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not found"}
            
        try:
            from qwen_agent.agents import CodeInterpreter
            
            interpreter = CodeInterpreter(
                llm={
                    'model': 'qwen-turbo',
                    'base_url': f'{self.chimera_url}/v1'
                }
            )
            return interpreter
        except Exception as e:
            return {"error": str(e)}


# Example usage
if __name__ == "__main__":
    bridge = QwenAgentBridge()
    
    print("Qwen-Agent Bridge")
    print("=" * 40)
    print(f"Qwen-Agent available: {bridge.qwen_available}")
    print()
    print("Available methods:")
    print("- create_react_agent()")
    print("- create_function_agent()") 
    print("- create_group_chat()")
    print("- run_browser_assistant()")
    print("- run_code_interpreter()")

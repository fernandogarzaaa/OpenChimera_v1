"""
CHIMERA Qwen-Agent Integration
Uses CHIMERA as the LLM backend for Qwen-Agent
"""
import os
import sys

# Setup path to Qwen-Agent
QWEN_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'appforge-main', 'Qwen-Agent')
if os.path.exists(QWEN_PATH):
    sys.path.insert(0, QWEN_PATH)

try:
    from qwen_agent.llm import get_chat_model
    from qwen_agent.agents import ReActChat, FnCallAgent, GroupChat
    QWEN_AVAILABLE = True
except ImportError:
    QWEN_AVAILABLE = False
    print("Qwen-Agent not found. Run: pip install -U qwen-agent")


class ChimeraQwenAgent:
    """
    Use CHIMERA as backend for Qwen-Agent
    
    Example:
        agent = ChimeraQwenAgent()
        response = agent.run("Analyze this code: def foo(): pass")
    """
    
    def __init__(
        self, 
        chimera_url: str = "http://localhost:7861",
        model: str = "qwen-turbo"
    ):
        self.chimera_url = chimera_url
        self.model = model
        
        if QWEN_AVAILABLE:
            self.llm = get_chat_model({
                'model': model,
                'model_server': 'openai',  # Use OpenAI-compatible API
                'api_key': 'chimera-local',
                'api_base': f'{chimera_url}/v1'
            })
    
    def chat(self, query: str, system: str = None) -> str:
        """Simple chat with Qwen-Agent"""
        if not QWEN_AVAILABLE:
            return "Qwen-Agent not installed"
            
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': query})
        
        response = self.llm.chat(messages)
        return response[-1].content
    
    def react_agent(self, query: str, tools: list = None):
        """Create a ReAct agent (reasoning + acting)"""
        if not QWEN_AVAILABLE:
            return None
            
        agent = ReActChat(
            llm={
                'model': self.model,
                'model_server': 'openai',
                'api_key': 'chimera-local',
                'api_base': f'{self.chimera_url}/v1'
            },
            tools=tools or []
        )
        
        return agent.run(query)
    
    def function_calling(self, query: str, functions: list):
        """Create a function-calling agent"""
        if not QWEN_AVAILABLE:
            return None
            
        agent = FnCallAgent(
            llm={
                'model': self.model,
                'model_server': 'openai', 
                'api_key': 'chimera-local',
                'api_base': f'{self.chimera_url}/v1'
            },
            function_list=functions
        )
        
        return agent.run(query)
    
    def group_chat(self, query: str, agent_configs: list):
        """Create a multi-agent group chat"""
        if not QWEN_AVAILABLE:
            return None
            
        # Create agents from configs
        agents = []
        for cfg in agent_configs:
            agents.append(
                ReActChat(
                    llm={
                        'model': cfg.get('model', self.model),
                        'model_server': 'openai',
                        'api_key': 'chimera-local',
                        'api_base': f'{self.chimera_url}/v1'
                    },
                    name=cfg.get('name', 'agent'),
                    description=cfg.get('description', '')
                )
            )
        
        group = GroupChat(
            llm={
                'model': self.model,
                'model_server': 'openai',
                'api_key': 'chimera-local', 
                'api_base': f'{self.chimera_url}/v1'
            },
            agents=agents
        )
        
        return group.run(query)


# Quick test
if __name__ == "__main__":
    print("CHIMERA + Qwen-Agent Bridge")
    print("=" * 40)
    
    if QWEN_AVAILABLE:
        agent = ChimeraQwenAgent()
        print("Testing chat...")
        # result = agent.chat("What is 2+2?")
        # print(f"Result: {result}")
        print("Ready!")
    else:
        print("Install: pip install qwen-agent")

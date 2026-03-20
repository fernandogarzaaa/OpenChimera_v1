"""
CHIMERA + Qwen-Agent Enhanced Integration
Full-featured multi-agent system with tools
"""
import os
import sys

# Add Qwen-Agent to path
QWEN_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'appforge-main', 'Qwen-Agent')
if os.path.exists(QWEN_PATH):
    sys.path.insert(0, QWEN_PATH)

try:
    from qwen_agent.llm import get_chat_model
    from qwen_agent.agents import (
        ReActChat, FnCallAgent, GroupChat, 
        BrowserAssistant, CodeInterpreter,
        Assistant
    )
    from qwen_agent.tools import (
        CodeInterpreter, Retrieval, WebSearch,
        PythonExecutor
    )
    QWEN_AVAILABLE = True
except ImportError as e:
    QWEN_AVAILABLE = False
    print(f"Qwen-Agent not found: {e}")
    print("Install with: pip install -U qwen-agent")


class ChimeraQwenEnhanced:
    """
    Enhanced CHIMERA + Qwen-Agent Integration
    
    Features:
    - Multi-model support (Qwen, Llama, etc.)
    - Function calling
    - Web search
    - Code interpretation
    - RAG (Retrieval)
    - Browser automation
    - Multimodal (images, video)
    """
    
    def __init__(
        self,
        chimera_url: str = "http://localhost:7861",
        model: str = "qwen-turbo"
    ):
        self.chimera_url = chimera_url
        self.model = model
        self.qwen_available = QWEN_AVAILABLE
        
        if QWEN_AVAILABLE:
            self.llm_config = {
                'model': model,
                'model_server': 'openai',
                'api_key': 'chimera-local',
                'api_base': f'{chimera_url}/v1'
            }
    
    # ========== BASIC CHAT ==========
    
    def chat(self, query: str, system: str = None) -> str:
        """Simple chat"""
        if not self.qwen_available:
            return "Qwen-Agent not installed"
            
        llm = get_chat_model(self.llm_config)
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': query})
        
        response = llm.chat(messages)
        return response[-1].content
    
    # ========== REACT AGENT ==========
    
    def react(
        self, 
        query: str, 
        tools: list = None,
        allow_code: bool = True
    ):
        """
        ReAct Agent - Reasoning + Acting
        
        Can use tools and think step by step
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not installed"}
        
        # Add built-in tools
        tool_list = tools or []
        
        if allow_code:
            # Add code interpreter
            tool_list.append(CodeInterpreter())
        
        agent = ReActChat(
            llm=self.llm_config,
            tools=tool_list
        )
        
        return agent.run(query)
    
    # ========== FUNCTION CALLING ==========
    
    def function_call(self, query: str, functions: list):
        """
        Function calling agent
        
        Define your own functions for the agent to call
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not installed"}
        
        agent = FnCallAgent(
            llm=self.llm_config,
            function_list=functions
        )
        
        return agent.run(query)
    
    # ========== GROUP CHAT ==========
    
    def group_chat(
        self,
        query: str,
        agents: list = None
    ):
        """
        Multi-agent group chat
        
        Multiple agents collaborate on a task
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not installed"}
        
        # Create agent configs
        agent_configs = agents or [
            {'name': 'researcher', 'description': 'Researches information'},
            {'name': 'analyst', 'description': 'Analyzes data'},
            {'name': 'writer', 'description': 'Writes the response'}
        ]
        
        qwen_agents = []
        for cfg in agent_configs:
            qwen_agents.append(
                ReActChat(
                    llm=self.llm_config,
                    name=cfg.get('name', 'agent'),
                    description=cfg.get('description', '')
                )
            )
        
        group = GroupChat(
            llm=self.llm_config,
            agents=qwen_agents
        )
        
        return group.run(query)
    
    # ========== CODE INTERPRETER ==========
    
    def code_interpreter(self, code: str = None, query: str = None):
        """
        Code Interpreter - Execute Python code
        
        Can run Python code in a sandbox
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not installed"}
        
        interpreter = CodeInterpreter(llm=self.llm_config)
        
        if code:
            # Run specific code
            return interpreter.run(code)
        elif query:
            # Generate and run code to answer query
            return interpreter.run(query)
    
    # ========== RAG (RETRIEVAL) ==========
    
    def rag(
        self,
        query: str,
        documents: list = None,
        file_paths: list = None
    ):
        """
        RAG - Retrieval Augmented Generation
        
        Search through documents and generate answer
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not installed"}
        
        # Use retrieval tool
        retrieval = Retrieval()
        
        # Add documents
        if documents:
            retrieval.add_documents(documents)
        
        # Add files
        if file_paths:
            for path in file_paths:
                retrieval.add_file(path)
        
        # Create agent with retrieval
        agent = Assistant(
            llm=self.llm_config,
            tools=[retrieval]
        )
        
        return agent.run(query)
    
    # ========== WEB SEARCH ==========
    
    def web_search(self, query: str, num_results: int = 5):
        """
        Web Search Agent
        
        Search the web for information
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not installed"}
        
        search_tool = WebSearch()
        results = search_tool.call(query)
        
        # Return top results
        return results[:num_results]
    
    # ========== BROWSER ASSISTANT ==========
    
    def browser(self, task: str):
        """
        Browser Assistant - AI-powered web browsing
        
        Can navigate, click, type, extract info from websites
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not installed"}
        
        assistant = BrowserAssistant(llm=self.llm_config)
        
        return assistant.run(task)
    
    # ========== MULTIMODAL ==========
    
    def multimodal(
        self,
        query: str,
        images: list = None,
        video: str = None,
        audio: str = None
    ):
        """
        Multimodal Agent
        
        Process images, video, and audio
        """
        if not self.qwen_available:
            return {"error": "Qwen-Agent not installed"}
        
        messages = [{'role': 'user', 'content': query}]
        
        # Add images
        if images:
            for img in images:
                messages.append({
                    'role': 'user',
                    'content': [{'image': img}, {'text': query}]
                })
        
        # Add video
        if video:
            messages.append({
                'role': 'user', 
                'content': [{'video': video}, {'text': query}]
            })
        
        # Add audio
        if audio:
            messages.append({
                'role': 'user',
                'content': [{'audio': audio}, {'text': query}]
            })
        
        # Use VL model
        vl_config = self.llm_config.copy()
        vl_config['model'] = 'qwen-vl-max'  # Vision-language model
        
        try:
            llm = get_chat_model(vl_config)
            response = llm.chat(messages)
            return response[-1].content
        except:
            # Fallback to regular chat
            return self.chat(query)


# ========== PREDEFINED AGENTS ==========

class ChimeraAgentFactory:
    """Factory for creating predefined agents"""
    
    @staticmethod
    def researcher(chimera_url="http://localhost:7861"):
        """Research Agent - finds and summarizes info"""
        return {
            'name': 'researcher',
            'description': 'Researches topics thoroughly',
            'system': 'You are a research assistant. Find comprehensive information and cite sources.'
        }
    
    @staticmethod
    def coder(chimera_url="http://localhost:7861"):
        """Coder Agent - writes and debugs code"""
        return {
            'name': 'coder',
            'description': 'Writes clean, efficient code',
            'system': 'You are a senior programmer. Write clean, tested, well-documented code.'
        }
    
    @staticmethod
    def analyst(chimera_url="http://localhost:7861"):
        """Analyst Agent - analyzes data"""
        return {
            'name': 'analyst',
            'description': 'Analyzes data and finds patterns',
            'system': 'You are a data analyst. Analyze data thoroughly and provide insights.'
        }
    
    @staticmethod
    def writer(chimera_url="http://localhost:7861"):
        """Writer Agent - creates content"""
        return {
            'name': 'writer',
            'description': 'Writes clear, engaging content',
            'system': 'You are a skilled writer. Create clear, engaging, well-structured content.'
        }
    
    @staticmethod
    def reviewer(chimera_url="http://localhost:7861"):
        """Reviewer Agent - reviews and improves content"""
        return {
            'name': 'reviewer',
            'description': 'Reviews and improves work',
            'system': 'You are a thorough reviewer. Provide constructive feedback and suggest improvements.'
        }


# Demo
if __name__ == "__main__":
    print("CHIMERA + Qwen-Agent Enhanced")
    print("=" * 50)
    print()
    
    if QWEN_AVAILABLE:
        chimera = ChimeraQwenEnhanced()
        
        print("Available methods:")
        print()
        print("Basic:")
        print("  .chat(query)                    - Simple chat")
        print()
        print("Advanced:")
        print("  .react(query)                   - ReAct agent")
        print("  .function_call(query, fns)      - Function calling")
        print("  .group_chat(query, agents)      - Multi-agent")
        print()
        print("Tools:")
        print("  .code_interpreter(code)          - Execute Python")
        print("  .rag(query, docs)               - Retrieval")
        print("  .web_search(query)               - Web search")
        print("  .browser(task)                  - Browser automation")
        print("  .multimodal(query, images=[])    - Images/video")
        print()
        print("Factory:")
        print("  ChimeraAgentFactory.researcher()")
        print("  ChimeraAgentFactory.coder()")
        print("  ChimeraAgentFactory.analyst()")
    else:
        print("Install: pip install -U qwen-agent")

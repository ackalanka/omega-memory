"""Example: Using OMEGA with LangChain / LangGraph agents.

OMEGA provides persistent, local-first memory with semantic search.
This example shows how to inject OMEGA memories as context into
a LangChain chain.

Requirements:
    pip install omega-memory[server] langchain-core langchain-openai
    omega setup
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from omega.integrations.langchain import OmegaMemory

# Initialize OMEGA memory
mem = OmegaMemory(project="my-project")

# Store some decisions (normally auto-captured by OMEGA hooks)
mem.save("We use PostgreSQL for the orders service because we need ACID transactions", event_type="decision")
mem.save("Always use early returns, never nest more than 2 levels", event_type="user_preference")
mem.save("Docker node_modules volume mount shadows container modules - use anonymous volume", event_type="lesson_learned")

# Later: recall relevant memories as context for a chain
llm = ChatOpenAI(model="gpt-4o-mini")

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful coding assistant. Relevant context from memory:\n{memory}"),
    ("human", "{input}"),
])

chain = prompt | llm

# OMEGA semantically matches "database" to the PostgreSQL decision
context = mem.recall_as_context("database choice for orders")
response = chain.invoke({"input": "What database should I use for the orders service?", "memory": context})
print(response.content)

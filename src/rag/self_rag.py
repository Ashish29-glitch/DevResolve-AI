"""
DevResolve AI - Self-RAG Engine for Ticket Solutions
Adapted from RunbookPilot's Self-RAG for developer issue resolution
"""
from typing import List, TypedDict, Literal, Annotated
import operator
import sqlite3
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from src.config import get_settings
from src.rag.vectorstore import get_retriever

ROOT = Path(__file__).resolve().parents[2]


class RAGState(TypedDict, total=False):
    ticket_title: str
    ticket_description: str
    assigned_team: str
    question: str
    docs: List[Document]
    relevant_docs: List[Document]
    context: str
    answer: str
    support_status: Literal["fully_supported", "partially_supported", "no_support", ""]
    evidence: List[str]
    usefulness: Literal["useful", "not_useful", ""]
    retrieval_rewrites: int
    source_mode: Literal["internal", "direct", "none"]
    trace: List[str]


class RelevanceDecision(BaseModel):
    is_relevant: bool


class SupportDecision(BaseModel):
    status: Literal["fully_supported", "partially_supported", "no_support"]
    evidence: List[str] = Field(default_factory=list)


class UsefulnessDecision(BaseModel):
    status: Literal["useful", "not_useful"]
    reason: str


class QueryRewrite(BaseModel):
    query: str


import json
import re

def _llm():
    s = get_settings()
    if not s.groq_api_key:
        raise RuntimeError("GROQ_API_KEY not configured")
    return ChatGroq(api_key=s.groq_api_key, model=s.groq_model, temperature=0)


def _call_json_llm(prompt_text: str, default: dict) -> dict:
    try:
        llm = _llm()
        resp = llm.invoke(f"{prompt_text}\n\nRespond ONLY with a valid JSON object, no explanation.")
        raw = resp.content.strip()
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return default
    except Exception as e:
        print(f"JSON LLM parse error: {e}")
        return default


def _trace(state: RAGState, item: str):
    return [*(state.get("trace") or []), item]


def _format_context(docs: List[Document]) -> str:
    blocks = []
    for i, d in enumerate(docs, 1):
        meta = d.metadata or {}
        head = f"[DOC {i}] {meta.get('title') or meta.get('document_name') or meta.get('source', '')}"
        if meta.get("page") is not None:
            head += f" | page {int(meta['page']) + 1}"
        blocks.append(f"{head}\n{d.page_content}")
    return "\n\n---\n\n".join(blocks)


# ─── Graph Nodes ─────────────────────────────────────────────────────────────

def build_question(state: RAGState):
    title = state.get("ticket_title", "")
    desc = state.get("ticket_description", "")
    team = state.get("assigned_team", "")
    q = f"[{team.upper()} ISSUE] {title}\n\nDetails: {desc}"
    return {"question": q, "trace": _trace(state, f"Built search query for {team} issue")}


def retrieve_internal(state: RAGState):
    q = state.get("question", "")
    retriever = get_retriever()
    docs = retriever.invoke(q)
    return {"docs": docs, "trace": _trace(state, f"Retrieved {len(docs)} docs from knowledge base")}


def grade_relevance(state: RAGState):
    q = state.get("question", "")
    docs = state.get("docs", [])
    relevant = []
    for doc in docs:
        prompt = f"You are grading if a document is relevant to this developer issue:\nIssue: {q}\n\nDocument:\n{doc.page_content[:1000]}\n\nReturn JSON: {{\"is_relevant\": true/false}}"
        decision = _call_json_llm(prompt, {"is_relevant": True})
        if decision.get("is_relevant", True):
            relevant.append(doc)
    context = _format_context(relevant) if relevant else ""
    return {
        "relevant_docs": relevant,
        "context": context,
        "trace": _trace(state, f"Graded relevance: {len(relevant)}/{len(docs)} docs relevant"),
    }


def generate_solution(state: RAGState):
    q = state.get("question", "")
    context = state.get("context", "")
    team = state.get("assigned_team", "unknown")

    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""You are a senior {team} developer and AI assistant for DevResolve AI.
Analyze the submitted issue and provide a structured, actionable solution.

Format your response as:
## Problem Analysis
[Brief analysis of the root cause]

## Suggested Solution
[Step-by-step solution with code snippets if applicable]

## Prevention Tips
[How to prevent this in future]

If documentation is provided, cite it. Be specific and practical."""),
        ("human", "Issue:\n{question}\n\nRelevant Documentation:\n{context}"),
    ])
    response = _llm().invoke(prompt.format_messages(question=q, context=context or "No specific documentation found — using general knowledge."))
    mode = "internal" if context else "direct"
    return {
        "answer": response.content,
        "source_mode": mode,
        "trace": _trace(state, f"Generated solution via {mode} knowledge"),
    }


def check_support(state: RAGState):
    answer = state.get("answer", "")
    context = state.get("context", "")
    if not context:
        return {"support_status": "no_support", "evidence": [], "trace": _trace(state, "Support: direct knowledge (no docs)")}

    prompt = f"Check if the answer is supported by the documentation:\nDocumentation:\n{context[:2500]}\n\nAnswer:\n{answer[:1500]}\n\nReturn JSON: {{\"status\": \"fully_supported\" or \"partially_supported\" or \"no_support\", \"evidence\": [\"quote1\"]}}"
    decision = _call_json_llm(prompt, {"status": "partially_supported", "evidence": []})
    status = decision.get("status", "partially_supported")
    return {
        "support_status": status,
        "evidence": decision.get("evidence", []),
        "trace": _trace(state, f"Support status: {status}"),
    }


def check_usefulness(state: RAGState):
    q = state.get("question", "")
    answer = state.get("answer", "")
    prompt = f"Is this solution useful and actionable for this issue?\nIssue: {q}\n\nSolution:\n{answer[:1500]}\n\nReturn JSON: {{\"status\": \"useful\" or \"not_useful\", \"reason\": \"short reason\"}}"
    decision = _call_json_llm(prompt, {"status": "useful", "reason": "actionable"})
    status = decision.get("status", "useful")
    return {
        "usefulness": status,
        "trace": _trace(state, f"Usefulness: {status}"),
    }


def rewrite_query(state: RAGState):
    q = state.get("question", "")
    prompt = f"Rewrite this developer issue query into technical keywords for documentation search:\n{q}\n\nReturn JSON: {{\"query\": \"keywords\"}}"
    out = _call_json_llm(prompt, {"query": q})
    rewritten = out.get("query", q)
    rewrites = state.get("retrieval_rewrites", 0) + 1
    return {
        "question": rewritten,
        "retrieval_rewrites": rewrites,
        "trace": _trace(state, f"Rewrote query (attempt {rewrites}): {rewritten[:80]}"),
    }


def no_answer(state: RAGState):
    team = state.get("assigned_team", "development")
    answer = f"""## AI Analysis
No specific documentation was found for this issue in the knowledge base.

## General Recommendation
Please review the {team} team's documentation and check:
1. Similar past tickets for reference
2. Official framework/library documentation
3. Stack Overflow or relevant technical communities

Consider uploading relevant documentation to improve future AI suggestions."""
    return {"answer": answer, "source_mode": "none", "trace": _trace(state, "No documentation match — general guidance provided")}


# ─── Routing ─────────────────────────────────────────────────────────────────

def route_after_relevance(state: RAGState):
    relevant = state.get("relevant_docs", [])
    rewrites = state.get("retrieval_rewrites", 0)
    s = get_settings()
    if relevant:
        return "generate"
    if rewrites < s.max_retrieval_rewrites:
        return "rewrite"
    return "no_answer"


def route_after_support(state: RAGState):
    status = state.get("support_status", "")
    rewrites = state.get("retrieval_rewrites", 0)
    s = get_settings()
    if status in ("fully_supported", "partially_supported", "no_support"):
        return "usefulness"
    if rewrites < s.max_support_retries:
        return "rewrite"
    return "usefulness"


def route_after_usefulness(state: RAGState):
    usefulness = state.get("usefulness", "")
    if usefulness == "useful":
        return "end"
    rewrites = state.get("retrieval_rewrites", 0)
    s = get_settings()
    if rewrites < s.max_retrieval_rewrites:
        return "rewrite"
    return "end"


# ─── Build Graph ─────────────────────────────────────────────────────────────

def build_ticket_rag_graph():
    g = StateGraph(RAGState)
    g.add_node("build_question", build_question)
    g.add_node("retrieve", retrieve_internal)
    g.add_node("grade", grade_relevance)
    g.add_node("generate", generate_solution)
    g.add_node("support", check_support)
    g.add_node("usefulness", check_usefulness)
    g.add_node("rewrite", rewrite_query)
    g.add_node("no_answer", no_answer)

    g.add_edge(START, "build_question")
    g.add_edge("build_question", "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", route_after_relevance, {
        "generate": "generate", "rewrite": "rewrite", "no_answer": "no_answer"
    })
    g.add_edge("rewrite", "retrieve")
    g.add_edge("generate", "support")
    g.add_conditional_edges("support", route_after_support, {
        "usefulness": "usefulness", "rewrite": "rewrite"
    })
    g.add_conditional_edges("usefulness", route_after_usefulness, {
        "end": END, "rewrite": "rewrite"
    })
    g.add_edge("no_answer", END)

    db_path = ROOT / "data" / "rag_memory.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return g.compile(checkpointer=checkpointer)


def _sources(docs: List[Document]):
    seen, out = set(), []
    for d in docs or []:
        m = d.metadata or {}
        key = (m.get("source"), m.get("page"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "title": m.get("title") or m.get("document_name") or "",
            "source": m.get("source") or "",
            "page": (int(m["page"]) + 1) if m.get("page") is not None else None,
        })
    return out


_graph = None


def solve_ticket(title: str, description: str, assigned_team: str, ticket_id: int) -> dict:
    """Main entry point: runs RAG pipeline on a ticket and returns solution."""
    global _graph
    if _graph is None:
        _graph = build_ticket_rag_graph()

    initial: RAGState = {
        "ticket_title": title,
        "ticket_description": description,
        "assigned_team": assigned_team,
        "question": "",
        "docs": [],
        "relevant_docs": [],
        "context": "",
        "answer": "",
        "support_status": "",
        "evidence": [],
        "usefulness": "",
        "retrieval_rewrites": 0,
        "source_mode": "internal",
        "trace": [],
    }
    result = _graph.invoke(
        initial,
        config={"configurable": {"thread_id": f"ticket_{ticket_id}"}, "recursion_limit": 40}
    )
    mode = result.get("source_mode", "none")
    route_map = {"internal": "Project Documentation", "direct": "General Knowledge", "none": "General Guidance"}
    return {
        "ai_solution": result.get("answer", ""),
        "ai_route": route_map.get(mode, mode),
        "support_status": result.get("support_status", ""),
        "usefulness": result.get("usefulness", ""),
        "sources": _sources(result.get("relevant_docs", [])),
        "trace": result.get("trace", []),
    }

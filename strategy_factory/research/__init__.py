"""
Research module for the PASTANA.

This module handles all Perplexity API interactions for company research,
including:
- Company profile research
- Industry analysis
- Competitor intelligence
- Technology landscape mapping
- Regulatory context
"""

from .perplexity_client import PerplexityClient
from .query_templates import QueryTemplates
from .model_selector import ModelSelector
from .orchestrator import ResearchOrchestrator
from .result_processor import ResultProcessor

__all__ = [
    "PerplexityClient",
    "QueryTemplates",
    "ModelSelector",
    "ResearchOrchestrator",
    "ResultProcessor",
]


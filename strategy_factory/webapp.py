"""
Full-featured web application for PASTANA.

Features:
- Home page to enter company name and start analysis
- Real-time progress tracking during pipeline execution
- Results viewer with proper markdown rendering
- Download links for generated files

Usage:
    python -m strategy_factory.webapp

Then open http://localhost:5000 in your browser.
"""

import json
import logging
import os
import queue
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify, Response, send_from_directory, send_file, session, redirect, url_for
from dotenv import load_dotenv
from functools import wraps

import markdown
from markdown.extensions.tables import TableExtension
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.toc import TocExtension

from strategy_factory.config import OUTPUT_DIR, DELIVERABLES
from strategy_factory.models import CompanyInput, ResearchMode, DeliverableStatus
from strategy_factory.progress_tracker import ProgressTracker, slugify

load_dotenv()

BRAND_NAME = "PASTANA"
SERVICE_PRICE = "R$ 1.000,00"
FOOTER_PHONE = os.getenv("PASTANA_PHONE", "telefone a definir")

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24))

# Authentication credentials from .env
APP_USERNAME = os.getenv('APP_USERNAME', 'admin')
APP_PASSWORD = os.getenv('APP_PASSWORD', 'admin')

# Store for active jobs and their progress
active_jobs = {}


# =============================================================================
# Authentication
# =============================================================================

def login_required(f):
    """Decorator to require login for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.context_processor
def inject_brand_context():
    return {
        "footer_phone": FOOTER_PHONE,
    }


def get_error_details(exception, phase="unknown"):
    """
    Parse exception and return user-friendly error details.

    Returns:
        dict with 'title', 'message', 'solution', 'technical'
    """
    error_str = str(exception).lower()
    error_type = type(exception).__name__

    # API Key errors
    if "api key" in error_str or "unauthorized" in error_str or "401" in error_str:
        if "perplexity" in error_str or phase == "research":
            return {
                "title": "Erro na API Perplexity",
                "message": "A chave de API do Perplexity está inválida ou não foi configurada.",
                "solution": "Verifique se PERPLEXITY_API_KEY está correta no arquivo .env e reinicie a aplicação.",
                "technical": f"{error_type}: {exception}"
            }
        elif "gemini" in error_str or phase == "synthesis":
            return {
                "title": "Erro na API Gemini",
                "message": "A chave de API do Google Gemini está inválida ou não foi configurada.",
                "solution": "Verifique se GEMINI_API_KEY está correta no arquivo .env e reinicie a aplicação.",
                "technical": f"{error_type}: {exception}"
            }

    # Rate limit / quota errors
    if "rate limit" in error_str or "quota" in error_str or "429" in error_str:
        return {
            "title": "Limite de Taxa Excedido",
            "message": "Você atingiu o limite de requisições da API.",
            "solution": "Aguarde alguns minutos antes de tentar novamente, ou verifique seus créditos na plataforma da API.",
            "technical": f"{error_type}: {exception}"
        }

    # Credit/billing errors
    if "credit" in error_str or "billing" in error_str or "payment" in error_str or "insufficient" in error_str:
        return {
            "title": "Sem Créditos na API",
            "message": "Sua conta da API não tem créditos suficientes.",
            "solution": "Adicione créditos na sua conta Perplexity (perplexity.ai) ou Google AI Studio (aistudio.google.com).",
            "technical": f"{error_type}: {exception}"
        }

    # Network errors
    if "connection" in error_str or "timeout" in error_str or "network" in error_str:
        return {
            "title": "Erro de Conexão",
            "message": "Não foi possível conectar ao serviço de API.",
            "solution": "Verifique sua conexão com a internet e tente novamente. Se persistir, o serviço pode estar temporariamente indisponível.",
            "technical": f"{error_type}: {exception}"
        }

    # File permission errors
    if "permission" in error_str or "permissionerror" in error_type.lower():
        return {
            "title": "Erro de Permissão",
            "message": "Não foi possível criar ou escrever arquivos.",
            "solution": "Verifique as permissões da pasta 'output/'. Se usando Docker, reconstrua a imagem com 'docker compose up -d --build'.",
            "technical": f"{error_type}: {exception}"
        }

    # Generic error
    return {
        "title": "Erro Inesperado",
        "message": f"Ocorreu um erro durante a {get_phase_name(phase)}.",
        "solution": "Tente novamente. Se o erro persistir, verifique os logs do servidor para mais detalhes.",
        "technical": f"{error_type}: {exception}"
    }


def get_phase_name(phase):
    """Get user-friendly phase name."""
    phase_names = {
        "research": "fase de pesquisa",
        "synthesis": "fase de síntese",
        "generation": "geração de documentos",
        "unknown": "execução"
    }
    return phase_names.get(phase, "execução")


# =============================================================================
# HTML Templates
# =============================================================================

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - PASTANA</title>
    <style>
        :root {
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --bg: #f8fafc;
            --card: #ffffff;
            --text: #1e293b;
            --border: #e2e8f0;
            --error: #ef4444;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 1rem;
        }

        .login-card {
            background: var(--card);
            padding: 2.5rem;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 100%;
            max-width: 400px;
        }

        h1 {
            color: var(--text);
            margin-bottom: 0.5rem;
            font-size: 1.75rem;
        }

        .subtitle {
            color: #64748b;
            margin-bottom: 2rem;
            font-size: 0.95rem;
        }

        .form-group {
            margin-bottom: 1.5rem;
        }

        label {
            display: block;
            margin-bottom: 0.5rem;
            color: var(--text);
            font-weight: 500;
            font-size: 0.9rem;
        }

        input {
            width: 100%;
            padding: 0.75rem;
            border: 2px solid var(--border);
            border-radius: 8px;
            font-size: 1rem;
            transition: border-color 0.2s;
        }

        input:focus {
            outline: none;
            border-color: var(--primary);
        }

        .btn {
            width: 100%;
            padding: 0.875rem;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }

        .btn:hover {
            background: var(--primary-dark);
        }

        .error {
            background: #fee;
            color: var(--error);
            padding: 0.75rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            font-size: 0.9rem;
            border: 1px solid #fcc;
        }

        .footer {
            text-align: center;
            margin-top: 2rem;
            color: #94a3b8;
            font-size: 0.85rem;
        }
    </style>
</head>
<body>
    <div class="login-card">
        <h1>🔐 PASTANA</h1>
        <p class="subtitle">Faça login para acessar o sistema</p>

        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}

        <form method="POST">
            <div class="form-group">
                <label for="username">Usuário</label>
                <input type="text" id="username" name="username" required autofocus>
            </div>

            <div class="form-group">
                <label for="password">Senha</label>
                <input type="password" id="password" name="password" required>
            </div>

            <button type="submit" class="btn">Entrar</button>
        </form>

        <div class="footer">
            PASTANA &copy; 2024<br>
            Telefone: {{ footer_phone|default('telefone a definir') }}
        </div>
    </div>
</body>
</html>
"""

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - PASTANA</title>
    <style>
        :root {
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --primary-light: #dbeafe;
            --bg: #f8fafc;
            --card: #ffffff;
            --text: #1e293b;
            --text-secondary: #64748b;
            --border: #e2e8f0;
            --success: #22c55e;
            --success-light: #dcfce7;
            --warning: #f59e0b;
            --error: #ef4444;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        header {
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            color: white;
            padding: 1.5rem 0;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        }

        header .container {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        header h1 {
            font-size: 1.5rem;
            font-weight: 600;
        }

        header a {
            color: white;
            text-decoration: none;
            opacity: 0.9;
            transition: opacity 0.15s;
        }

        header a:hover {
            opacity: 1;
        }

        .logout-btn {
            background: rgba(255,255,255,0.2);
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.9rem;
            border: 1px solid rgba(255,255,255,0.3);
            transition: background 0.2s;
        }

        .logout-btn:hover {
            background: rgba(255,255,255,0.3);
            opacity: 1;
        }

        .card {
            background: var(--card);
            border-radius: 12px;
            padding: 2rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 1.5rem;
        }

        .card h2 {
            font-size: 1.25rem;
            margin-bottom: 1rem;
            color: var(--text);
        }

        .form-group {
            margin-bottom: 1.5rem;
        }

        .form-group label {
            display: block;
            font-weight: 500;
            margin-bottom: 0.5rem;
            color: var(--text);
        }

        .form-group small {
            display: block;
            color: var(--text-secondary);
            font-size: 0.875rem;
            margin-top: 0.25rem;
        }

        input[type="text"], textarea, select {
            width: 100%;
            padding: 0.75rem 1rem;
            border: 1px solid var(--border);
            border-radius: 8px;
            font-size: 1rem;
            transition: border-color 0.15s, box-shadow 0.15s;
        }

        input[type="text"]:focus, textarea:focus, select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px var(--primary-light);
        }

        textarea {
            min-height: 100px;
            resize: vertical;
        }

        .btn {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem 1.5rem;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.15s, transform 0.1s;
        }

        .btn:hover {
            background: var(--primary-dark);
        }

        .btn:active {
            transform: scale(0.98);
        }

        .btn:disabled {
            background: var(--text-secondary);
            cursor: not-allowed;
        }

        .btn-secondary {
            background: var(--bg);
            color: var(--text);
            border: 1px solid var(--border);
        }

        .btn-secondary:hover {
            background: var(--border);
        }

        .radio-group {
            display: flex;
            gap: 1rem;
        }

        .radio-option {
            flex: 1;
            padding: 1rem;
            border: 2px solid var(--border);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.15s;
        }

        .radio-option:hover {
            border-color: var(--primary-light);
        }

        .radio-option.selected {
            border-color: var(--primary);
            background: var(--primary-light);
        }

        .radio-option input {
            display: none;
        }

        .radio-option h4 {
            font-size: 1rem;
            margin-bottom: 0.25rem;
        }

        .radio-option p {
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin: 0;
        }

        /* Progress page styles */
        .progress-container {
            max-width: 800px;
            margin: 3rem auto;
        }

        .progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
        }

        .progress-header h2 {
            font-size: 1.75rem;
            margin-bottom: 0.5rem;
        }

        .progress-header p {
            color: var(--text-secondary);
        }

        .phase-list {
            list-style: none;
        }

        .phase-item {
            display: flex;
            align-items: flex-start;
            gap: 1rem;
            padding: 1.25rem;
            background: var(--card);
            border-radius: 8px;
            margin-bottom: 0.75rem;
            border: 1px solid var(--border);
            transition: all 0.3s;
        }

        .phase-item.active {
            border-color: var(--primary);
            box-shadow: 0 0 0 3px var(--primary-light);
        }

        .phase-item.completed {
            border-color: var(--success);
            background: var(--success-light);
        }

        .phase-icon {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1rem;
            flex-shrink: 0;
        }

        .phase-item.pending .phase-icon {
            background: var(--border);
            color: var(--text-secondary);
        }

        .phase-item.active .phase-icon {
            background: var(--primary);
            color: white;
            animation: pulse 1.5s infinite;
        }

        .phase-item.completed .phase-icon {
            background: var(--success);
            color: white;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }

        .phase-content {
            flex: 1;
        }

        .phase-content h4 {
            font-size: 1rem;
            margin-bottom: 0.25rem;
        }

        .phase-content p {
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin: 0;
        }

        .phase-progress {
            margin-top: 0.75rem;
        }

        .progress-bar {
            height: 6px;
            background: var(--border);
            border-radius: 3px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            background: var(--primary);
            border-radius: 3px;
            transition: width 0.3s;
        }

        .progress-text {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }

        .spinner {
            width: 20px;
            height: 20px;
            border: 2px solid var(--border);
            border-top-color: var(--primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Results page - sidebar layout */
        .results-layout {
            display: grid;
            grid-template-columns: 300px 1fr;
            gap: 2rem;
            min-height: calc(100vh - 200px);
        }

        .sidebar {
            background: var(--card);
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            height: fit-content;
            position: sticky;
            top: 1rem;
        }

        .sidebar h3 {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            margin-bottom: 0.75rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid var(--border);
        }

        .nav-list {
            list-style: none;
            margin-bottom: 1.5rem;
        }

        .nav-list li {
            margin-bottom: 0.25rem;
        }

        .nav-list a {
            display: block;
            padding: 0.5rem 0.75rem;
            color: var(--text);
            text-decoration: none;
            border-radius: 6px;
            font-size: 0.875rem;
            transition: all 0.15s;
        }

        .nav-list a:hover {
            background: var(--bg);
            color: var(--primary);
        }

        .nav-list a.active {
            background: var(--primary);
            color: white;
        }

        .download-btn {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 0.75rem;
            background: var(--bg);
            border-radius: 6px;
            text-decoration: none;
            color: var(--text);
            font-size: 0.875rem;
            margin-bottom: 0.5rem;
            transition: all 0.15s;
        }

        .download-btn:hover {
            background: #64748b;
            color: white;
        }

        .download-btn .size {
            margin-left: auto;
            opacity: 0.6;
            font-size: 0.75rem;
        }

        .content {
            background: var(--card);
            border-radius: 12px;
            padding: 2rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        /* Markdown content styling */
        .markdown-content h1 { font-size: 1.75rem; margin-top: 0; margin-bottom: 1rem; }
        .markdown-content h2 { font-size: 1.5rem; margin-top: 2rem; margin-bottom: 0.75rem; border-bottom: 2px solid var(--border); padding-bottom: 0.5rem; }
        .markdown-content h3 { font-size: 1.25rem; margin-top: 1.5rem; margin-bottom: 0.5rem; }
        .markdown-content h4 { font-size: 1.1rem; margin-top: 1.25rem; margin-bottom: 0.5rem; }

        .markdown-content p { margin-bottom: 1rem; }

        .markdown-content ul, .markdown-content ol {
            margin-bottom: 1rem;
            padding-left: 1.5rem;
        }

        .markdown-content li { margin-bottom: 0.5rem; }

        .markdown-content table {
            width: 100%;
            border-collapse: collapse;
            margin: 1.5rem 0;
            font-size: 0.9rem;
        }

        .markdown-content th, .markdown-content td {
            padding: 0.75rem 1rem;
            text-align: left;
            border: 1px solid var(--border);
        }

        .markdown-content th {
            background: var(--bg);
            font-weight: 600;
        }

        .markdown-content tr:nth-child(even) {
            background: var(--bg);
        }

        .markdown-content code {
            background: var(--bg);
            padding: 0.2rem 0.4rem;
            border-radius: 4px;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.875em;
        }

        .markdown-content pre {
            background: #1e293b;
            color: #e2e8f0;
            padding: 1rem;
            border-radius: 8px;
            overflow-x: auto;
            margin: 1rem 0;
        }

        .markdown-content pre code {
            background: none;
            padding: 0;
            color: inherit;
        }

        .markdown-content blockquote {
            border-left: 4px solid var(--primary);
            padding-left: 1rem;
            margin: 1rem 0;
            color: var(--text-secondary);
        }

        .markdown-content hr {
            border: none;
            border-top: 1px solid var(--border);
            margin: 2rem 0;
        }

        /* Diagrams grid */
        .diagrams-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 1.5rem;
        }

        .diagram-card {
            background: var(--bg);
            border-radius: 8px;
            padding: 1rem;
            text-align: center;
        }

        .diagram-card img {
            max-width: 100%;
            height: auto;
            border-radius: 4px;
            margin-bottom: 0.5rem;
            cursor: pointer;
            transition: transform 0.2s;
        }

        .diagram-card img:hover {
            transform: scale(1.02);
        }

        .diagram-card h4 {
            margin: 0;
            font-size: 0.875rem;
        }

        /* Stats header */
        .stats-bar {
            display: flex;
            gap: 2rem;
            padding: 1rem 1.5rem;
            background: var(--card);
            border-radius: 8px;
            margin-bottom: 1.5rem;
        }

        .stat-item {
            text-align: center;
        }

        .stat-value {
            font-size: 1.5rem;
            font-weight: 600;
            color: var(--primary);
        }

        .stat-label {
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-transform: uppercase;
        }

        /* Companies list */
        .companies-list {
            display: grid;
            gap: 1rem;
        }

        .company-card {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1rem 1.5rem;
            background: var(--card);
            border-radius: 8px;
            border: 1px solid var(--border);
            text-decoration: none;
            color: var(--text);
            transition: all 0.15s;
        }

        .company-card:hover {
            border-color: var(--primary);
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }

        .company-info h3 {
            font-size: 1.1rem;
            margin-bottom: 0.25rem;
        }

        .company-info p {
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin: 0;
        }

        .company-meta {
            text-align: right;
        }

        .company-meta .progress {
            font-weight: 600;
            color: var(--success);
        }

        .company-meta .cost {
            font-size: 0.875rem;
            color: var(--text-secondary);
        }

        /* Running jobs list */
        .running-jobs-list {
            display: grid;
            gap: 1rem;
        }

        .running-job-card {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1rem 1.5rem;
            background: #fef3c7;
            border-radius: 8px;
            border: 2px solid #fbbf24;
        }

        .job-actions {
            display: flex;
            gap: 0.5rem;
            align-items: center;
        }

        .btn-cancel {
            padding: 0.5rem 1rem;
            background: #dc2626;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.875rem;
            transition: background 0.15s;
        }

        .btn-cancel:hover {
            background: #b91c1c;
        }

        .company-card-wrapper {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .company-actions {
            display: flex;
            gap: 0.5rem;
            padding-left: 1.5rem;
        }

        .btn-continue {
            padding: 0.5rem 1rem;
            background: #059669;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.875rem;
            transition: background 0.15s;
        }

        .btn-continue:hover {
            background: #047857;
        }

        .price-banner {
            background: #111827;
            color: white;
            border-radius: 8px;
            padding: 1rem 1.25rem;
            margin-bottom: 1rem;
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: center;
            border: 1px solid rgba(255,255,255,0.08);
        }

        .price-banner strong {
            font-size: 1.5rem;
            white-space: nowrap;
        }

        footer.site-footer {
            max-width: 1400px;
            margin: 0 auto;
            padding: 1.5rem 2rem 2rem;
            color: var(--text-secondary);
            font-size: 0.9rem;
            text-align: center;
        }

        @media (max-width: 900px) {
            .results-layout {
                grid-template-columns: 1fr;
            }

            .sidebar {
                position: relative;
                top: 0;
            }
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <a href="/"><h1>PASTANA</h1></a>
            <nav>
                <a href="/">Nova Análise</a>
                <a href="/logout" class="logout-btn">Sair</a>
            </nav>
        </div>
    </header>

    <div class="container">
        {{ content|safe }}
    </div>

    <footer class="site-footer">
        PASTANA &copy; 2024 | Telefone: {{ footer_phone|default('telefone a definir') }}
    </footer>

    {{ scripts|safe }}
</body>
</html>
"""

HOME_CONTENT = """
<div style="max-width: 700px; margin: 2rem auto;">
    <div class="price-banner">
        <span>Consultoria estratégica de IA PASTANA</span>
        <strong>R$ 1.000,00</strong>
    </div>

    <div class="card" style="margin-bottom: 1rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
            <h3 style="margin: 0;">Status das APIs</h3>
            <button onclick="checkAPIs()" class="btn btn-secondary" style="padding: 0.5rem 1rem;" id="check-btn">
                🔍 Testar APIs
            </button>
        </div>
        <div id="api-status" style="display: none;">
            <div style="background: #f8fafc; padding: 1rem; border-radius: 4px; margin-bottom: 0.5rem;">
                <div style="display: flex; align-items: center; justify-content: space-between;">
                    <span><strong>Perplexity AI</strong> (Fase 1: Research)</span>
                    <span id="perplexity-status">⏳ Testando...</span>
                </div>
                <small id="perplexity-msg" style="color: #64748b; display: block; margin-top: 0.25rem;"></small>
            </div>
            <div style="background: #f8fafc; padding: 1rem; border-radius: 4px;">
                <div style="display: flex; align-items: center; justify-content: space-between;">
                    <span><strong>Google Gemini</strong> (Fase 2: Synthesis)</span>
                    <span id="gemini-status">⏳ Testando...</span>
                </div>
                <small id="gemini-msg" style="color: #64748b; display: block; margin-top: 0.25rem;"></small>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>Gerar Estratégia de IA</h2>
        <p style="color: var(--text-secondary); margin-bottom: 1.5rem;">
            Digite o nome de uma empresa para gerar documentos estratégicos completos de IA incluindo
            roadmaps, avaliações de maturidade, análise de ROI e guias de implementação.
        </p>

        <form id="analysis-form" action="/start" method="POST">
            <div class="form-group">
                <label for="company">Nome da Empresa *</label>
                <input type="text" id="company" name="company" placeholder="ex: Nubank, Magazine Luiza, iFood" required>
            </div>

            <div class="form-group">
                <label for="context">Contexto Adicional</label>
                <textarea id="context" name="context" placeholder="Opcional: Setor, tamanho da empresa, objetivos específicos, stack tecnológico atual, etc."></textarea>
                <small>Ajude-nos a personalizar a análise para sua situação específica</small>
            </div>

            <div class="form-group">
                <label>Modo de Pesquisa</label>
                <div class="radio-group">
                    <label class="radio-option selected" id="mode-quick">
                        <input type="radio" name="mode" value="quick" checked>
                        <h4>Rápido</h4>
                        <p>~$0.05 | 2-3 minutos</p>
                    </label>
                    <label class="radio-option" id="mode-comprehensive">
                        <input type="radio" name="mode" value="comprehensive">
                        <h4>Completo</h4>
                        <p>~$0.50 | 5-10 minutos</p>
                    </label>
                </div>
            </div>

            <button type="submit" class="btn" style="width: 100%; margin-top: 1rem;">
                Iniciar Análise
            </button>
        </form>
    </div>

    {% if running_jobs %}
    <div class="card">
        <h2>🔄 Análises em Andamento</h2>
        <div class="running-jobs-list">
            {% for job in running_jobs %}
            <div class="running-job-card" data-job-id="{{ job.job_id }}">
                <div class="company-info">
                    <h3>{{ job.company_name }}</h3>
                    <p>⏳ Processando...</p>
                </div>
                <div class="job-actions">
                    <button onclick="cancelJob('{{ job.job_id }}')" class="btn-cancel">
                        ❌ Cancelar
                    </button>
                    {% if job.company_slug %}
                    <a href="/results/{{ job.company_slug }}" class="btn-secondary" style="padding: 0.5rem 1rem; text-decoration: none;">
                        👁️ Ver Progresso
                    </a>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}

    {% if companies %}
    <div class="card">
        <h2>Análises Anteriores</h2>
        <div class="companies-list">
            {% for company in companies %}
            <div class="company-card-wrapper">
                <a href="/results/{{ company.slug }}" class="company-card">
                    <div class="company-info">
                        <h3>{{ company.name }}</h3>
                        <p>{{ company.phase }}</p>
                        {% if company.version_date %}
                        <small style="color: #64748b; font-size: 0.8rem;">
                            📅 {{ company.version_date.strftime("%d/%m/%Y %H:%M") }}
                        </small>
                        {% endif %}
                    </div>
                    <div class="company-meta">
                        <div class="progress">{{ company.progress }}%</div>
                        <div class="cost">${{ "%.4f"|format(company.cost) }}</div>
                    </div>
                </a>
                {% if company.progress < 100 %}
                <div class="company-actions">
                    <form action="/continue/{{ company.slug }}" method="POST" style="display: inline;">
                        <button type="submit" class="btn-continue" onclick="return confirm('Deseja continuar esta análise de onde parou?')">
                            ▶️ Continuar
                        </button>
                    </form>
                </div>
                {% endif %}
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}
</div>
"""

HOME_SCRIPTS = """
<script>
    document.querySelectorAll('.radio-option').forEach(option => {
        option.addEventListener('click', function() {
            document.querySelectorAll('.radio-option').forEach(o => o.classList.remove('selected'));
            this.classList.add('selected');
            this.querySelector('input').checked = true;
        });
    });

    function checkAPIs() {
        const btn = document.getElementById('check-btn');
        const statusDiv = document.getElementById('api-status');

        btn.disabled = true;
        btn.textContent = '⏳ Testando...';
        statusDiv.style.display = 'block';

        // Reset status
        document.getElementById('perplexity-status').textContent = '⏳ Testando...';
        document.getElementById('gemini-status').textContent = '⏳ Testando...';
        document.getElementById('perplexity-msg').textContent = '';
        document.getElementById('gemini-msg').textContent = '';

        fetch('/api/health-check')
            .then(response => response.json())
            .then(data => {
                // Perplexity
                const pStatus = document.getElementById('perplexity-status');
                const pMsg = document.getElementById('perplexity-msg');
                if (data.perplexity.status === 'ok') {
                    pStatus.textContent = '✅ OK';
                    pStatus.style.color = '#059669';
                } else if (data.perplexity.status === 'not_configured') {
                    pStatus.textContent = '⚙️ Não configurada';
                    pStatus.style.color = '#64748b';
                } else {
                    pStatus.textContent = '❌ Erro';
                    pStatus.style.color = '#dc2626';
                }
                pMsg.textContent = data.perplexity.message;
                if (data.perplexity.status === 'error') {
                    pMsg.style.color = '#dc2626';
                }

                // Gemini
                const gStatus = document.getElementById('gemini-status');
                const gMsg = document.getElementById('gemini-msg');
                if (data.gemini.status === 'ok') {
                    gStatus.textContent = '✅ OK';
                    gStatus.style.color = '#059669';
                } else if (data.gemini.status === 'not_configured') {
                    gStatus.textContent = '⚙️ Não configurada';
                    gStatus.style.color = '#64748b';
                } else if (data.gemini.status === 'warning') {
                    gStatus.textContent = '⚠️ Aviso';
                    gStatus.style.color = '#f59e0b';
                } else {
                    gStatus.textContent = '❌ Erro';
                    gStatus.style.color = '#dc2626';
                }
                gMsg.textContent = data.gemini.message;
                if (data.gemini.status === 'error') {
                    gMsg.style.color = '#dc2626';
                } else if (data.gemini.status === 'warning') {
                    gMsg.style.color = '#f59e0b';
                }

                btn.disabled = false;
                btn.textContent = '🔍 Testar APIs';
            })
            .catch(err => {
                alert('Erro ao testar APIs: ' + err);
                btn.disabled = false;
                btn.textContent = '🔍 Testar APIs';
            });
    }

    function cancelJob(jobId) {
        if (!confirm('Tem certeza que deseja cancelar esta análise?')) {
            return;
        }

        fetch('/cancel/' + jobId, {
            method: 'POST',
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert(data.message);
                // Remove the job card from the UI
                const jobCard = document.querySelector(`[data-job-id="${jobId}"]`);
                if (jobCard) {
                    jobCard.remove();
                }
                // Reload page if no more running jobs
                const runningJobs = document.querySelectorAll('.running-job-card');
                if (runningJobs.length === 0) {
                    location.reload();
                }
            } else {
                alert('Erro ao cancelar: ' + (data.error || 'Erro desconhecido'));
            }
        })
        .catch(err => {
            alert('Erro ao cancelar análise: ' + err);
        });
    }
</script>
"""

PROGRESS_CONTENT = """
<div class="progress-container">
    <div class="progress-header">
        <div>
            <h2>Analisando {{ company_name }}</h2>
            <p id="status-text">Inicializando...</p>
        </div>
        <button onclick="cancelAnalysis()" class="btn-cancel" id="cancel-btn">
            ❌ Cancelar Análise
        </button>
    </div>

    <div class="card">
        <ul class="phase-list" id="phase-list">
            <li class="phase-item active" id="phase-research">
                <div class="phase-icon"><div class="spinner"></div></div>
                <div class="phase-content">
                    <h4>Fase de Pesquisa</h4>
                    <p id="research-status">Coletando informações da empresa...</p>
                    <div class="phase-progress">
                        <div class="progress-bar"><div class="progress-fill" id="research-progress" style="width: 0%"></div></div>
                        <div class="progress-text" id="research-text">Iniciando...</div>
                    </div>
                </div>
            </li>
            <li class="phase-item pending" id="phase-synthesis">
                <div class="phase-icon">2</div>
                <div class="phase-content">
                    <h4>Fase de Síntese</h4>
                    <p id="synthesis-status">Aguardando...</p>
                    <div class="phase-progress" style="display: none;">
                        <div class="progress-bar"><div class="progress-fill" id="synthesis-progress" style="width: 0%"></div></div>
                        <div class="progress-text" id="synthesis-text"></div>
                    </div>
                </div>
            </li>
            <li class="phase-item pending" id="phase-generation">
                <div class="phase-icon">3</div>
                <div class="phase-content">
                    <h4>Geração de Documentos</h4>
                    <p id="generation-status">Aguardando...</p>
                    <div class="phase-progress" style="display: none;">
                        <div class="progress-bar"><div class="progress-fill" id="generation-progress" style="width: 0%"></div></div>
                        <div class="progress-text" id="generation-text"></div>
                    </div>
                </div>
            </li>
        </ul>
    </div>

    <div id="error-container" style="display: none;">
        <div class="card" style="border-color: var(--error); background: #fef2f2;">
            <h2 style="color: var(--error); margin-bottom: 1rem;">
                <span id="error-title">Erro</span>
            </h2>

            <div style="background: white; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                <h4 style="color: #64748b; margin-bottom: 0.5rem;">O que aconteceu:</h4>
                <p id="error-message" style="color: var(--text); margin: 0;"></p>
            </div>

            <div style="background: #fffbeb; border-left: 4px solid #f59e0b; padding: 1rem; border-radius: 4px; margin-bottom: 1rem;">
                <h4 style="color: #92400e; margin-bottom: 0.5rem;">💡 Como resolver:</h4>
                <p id="error-solution" style="color: #78350f; margin: 0;"></p>
            </div>

            <details style="margin-bottom: 1rem;">
                <summary style="cursor: pointer; color: #64748b; font-size: 0.9rem;">Detalhes técnicos</summary>
                <pre id="error-technical" style="background: #f1f5f9; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem; margin-top: 0.5rem; color: #334155;"></pre>
            </details>

            <div style="display: flex; gap: 1rem;">
                <a href="/" class="btn" style="flex: 1;">Tentar Novamente</a>
                <button onclick="copyErrorDetails()" class="btn btn-secondary" style="flex: 1;">Copiar Detalhes</button>
            </div>
        </div>
    </div>
</div>
"""

PROGRESS_SCRIPTS = """
<script>
    const jobId = '{{ job_id }}';
    let eventSource;

    function updatePhase(phaseId, status, isActive, isCompleted) {
        const phase = document.getElementById('phase-' + phaseId);
        phase.classList.remove('pending', 'active', 'completed');

        if (isCompleted) {
            phase.classList.add('completed');
            phase.querySelector('.phase-icon').innerHTML = '&#10003;';
        } else if (isActive) {
            phase.classList.add('active');
            phase.querySelector('.phase-icon').innerHTML = '<div class="spinner"></div>';
            phase.querySelector('.phase-progress').style.display = 'block';
        } else {
            phase.classList.add('pending');
        }

        document.getElementById(phaseId + '-status').textContent = status;
    }

    function updateProgress(phaseId, progress, text) {
        document.getElementById(phaseId + '-progress').style.width = progress + '%';
        document.getElementById(phaseId + '-text').textContent = text;
    }

    function startEventStream() {
        eventSource = new EventSource('/progress/' + jobId);

        eventSource.onmessage = function(event) {
            const data = JSON.parse(event.data);
            console.log('Progress update:', data);

            document.getElementById('status-text').textContent = data.message || 'Processing...';

            if (data.phase === 'research') {
                updatePhase('research', data.status || 'Researching...', true, data.completed);
                if (data.progress !== undefined) {
                    updateProgress('research', data.progress, data.detail || '');
                }
            } else if (data.phase === 'synthesis') {
                updatePhase('research', 'Complete', false, true);
                updatePhase('synthesis', data.status || 'Synthesizing...', true, data.completed);
                if (data.progress !== undefined) {
                    updateProgress('synthesis', data.progress, data.detail || '');
                }
            } else if (data.phase === 'generation') {
                updatePhase('synthesis', 'Complete', false, true);
                updatePhase('generation', data.status || 'Generating...', true, data.completed);
                if (data.progress !== undefined) {
                    updateProgress('generation', data.progress, data.detail || '');
                }
            }

            if (data.complete) {
                eventSource.close();
                updatePhase('generation', 'Complete', false, true);
                document.getElementById('status-text').textContent = 'Analysis complete!';
                setTimeout(() => {
                    window.location.href = '/results/' + data.company_slug;
                }, 1000);
            }

            if (data.error) {
                eventSource.close();
                document.getElementById('error-container').style.display = 'block';

                // Display detailed error information
                document.getElementById('error-title').textContent = data.error_title || 'Erro';
                document.getElementById('error-message').textContent = data.error_message || data.error;
                document.getElementById('error-solution').textContent = data.error_solution || 'Tente novamente.';
                document.getElementById('error-technical').textContent = data.error_technical || data.error;

                document.getElementById('status-text').textContent = 'Erro durante a execução';

                // Hide all phase indicators
                document.querySelectorAll('.phase-item').forEach(phase => {
                    phase.querySelector('.phase-icon').innerHTML = '';
                });
            }
        };

        eventSource.onerror = function(err) {
            console.error('EventSource error:', err);
        };
    }

    function copyErrorDetails() {
        const title = document.getElementById('error-title').textContent;
        const message = document.getElementById('error-message').textContent;
        const solution = document.getElementById('error-solution').textContent;
        const technical = document.getElementById('error-technical').textContent;

        const errorText = `
ERRO: ${title}

O que aconteceu:
${message}

Como resolver:
${solution}

Detalhes técnicos:
${technical}
        `.trim();

        navigator.clipboard.writeText(errorText).then(() => {
            const btn = event.target;
            const originalText = btn.textContent;
            btn.textContent = '✓ Copiado!';
            setTimeout(() => {
                btn.textContent = originalText;
            }, 2000);
        }).catch(err => {
            console.error('Erro ao copiar:', err);
            alert('Erro ao copiar. Use Ctrl+C manualmente.');
        });
    }

    function cancelAnalysis() {
        if (!confirm('Tem certeza que deseja cancelar esta análise?')) {
            return;
        }

        const cancelBtn = document.getElementById('cancel-btn');
        cancelBtn.disabled = true;
        cancelBtn.textContent = '⏳ Cancelando...';

        fetch('/cancel/' + jobId, {
            method: 'POST',
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.getElementById('status-text').textContent = 'Análise cancelada';
                if (eventSource) {
                    eventSource.close();
                }
                setTimeout(() => {
                    window.location.href = '/';
                }, 1500);
            } else {
                alert('Erro ao cancelar: ' + (data.error || 'Erro desconhecido'));
                cancelBtn.disabled = false;
                cancelBtn.textContent = '❌ Cancelar Análise';
            }
        })
        .catch(err => {
            alert('Erro ao cancelar análise: ' + err);
            cancelBtn.disabled = false;
            cancelBtn.textContent = '❌ Cancelar Análise';
        });
    }

    startEventStream();
</script>
"""


# =============================================================================
# Routes
# =============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        if username == APP_USERNAME and password == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            from jinja2 import Template
            return render_template_string(
                Template(LOGIN_TEMPLATE).render(error="Usuário ou senha incorretos", footer_phone=FOOTER_PHONE)
            )

    # If already logged in, redirect to home
    if session.get('logged_in'):
        return redirect(url_for('home'))

    from jinja2 import Template
    return render_template_string(Template(LOGIN_TEMPLATE).render(footer_phone=FOOTER_PHONE))


@app.route('/logout')
def logout():
    """Logout and redirect to login."""
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/api/health-check')
@login_required
def health_check():
    """Check if APIs are working."""
    import os

    results = {
        "perplexity": {"status": "unknown", "message": "", "configured": False},
        "gemini": {"status": "unknown", "message": "", "configured": False}
    }

    # Check Perplexity
    perplexity_key = os.getenv('PERPLEXITY_API_KEY', '')
    if perplexity_key and not perplexity_key.startswith('pplx-your'):
        results["perplexity"]["configured"] = True
        try:
            from strategy_factory.research.perplexity_client import PerplexityClient
            from strategy_factory.config import PerplexityModel
            client = PerplexityClient()
            # Try a minimal search
            response = client.search("test", max_results=1, model=PerplexityModel.SONAR)
            if response and response.result_count > 0:
                results["perplexity"]["status"] = "ok"
                results["perplexity"]["message"] = "API funcionando corretamente"
            elif response and response.error:
                results["perplexity"]["status"] = "error"
                results["perplexity"]["message"] = f"Erro: {response.error[:100]}"
            else:
                results["perplexity"]["status"] = "ok"
                results["perplexity"]["message"] = "API funcionando (sem resultados de teste)"
        except Exception as e:
            results["perplexity"]["status"] = "error"
            error_str = str(e).lower()
            if "401" in error_str or "unauthorized" in error_str or "api key" in error_str:
                results["perplexity"]["message"] = "Chave de API inválida"
            elif "429" in error_str or "rate limit" in error_str:
                results["perplexity"]["message"] = "Limite de taxa excedido"
            elif "credit" in error_str or "quota" in error_str or "billing" in error_str:
                results["perplexity"]["message"] = "Sem créditos na conta"
            else:
                results["perplexity"]["message"] = f"Erro: {str(e)[:100]}"
    else:
        results["perplexity"]["configured"] = False
        results["perplexity"]["status"] = "not_configured"
        results["perplexity"]["message"] = "Chave de API não configurada"

    # Check Gemini
    gemini_key = os.getenv('GEMINI_API_KEY', '')
    if gemini_key and not gemini_key.startswith('AIzaSy-your'):
        results["gemini"]["configured"] = True
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel('gemini-2.0-flash-exp')

            # Try a simple generation (avoid safety filters)
            response = model.generate_content(
                "What is 2+2? Answer with just the number.",
                generation_config=genai.GenerationConfig(max_output_tokens=10)
            )

            # Check if response has text
            if hasattr(response, 'text') and response.text:
                results["gemini"]["status"] = "ok"
                results["gemini"]["message"] = "API funcionando corretamente"
            elif hasattr(response, 'prompt_feedback'):
                # Check safety ratings
                feedback = response.prompt_feedback
                if hasattr(feedback, 'block_reason'):
                    results["gemini"]["status"] = "warning"
                    results["gemini"]["message"] = f"API OK mas conteúdo bloqueado: {feedback.block_reason}"
                else:
                    results["gemini"]["status"] = "ok"
                    results["gemini"]["message"] = "API funcionando (resposta vazia)"
            else:
                results["gemini"]["status"] = "error"
                results["gemini"]["message"] = "Resposta sem texto da API"

        except Exception as e:
            results["gemini"]["status"] = "error"
            error_str = str(e).lower()

            if "api_key" in error_str or "api key" in error_str or "invalid" in error_str:
                results["gemini"]["message"] = "Chave de API inválida"
            elif "429" in error_str or "rate limit" in error_str:
                results["gemini"]["message"] = "Limite de taxa excedido"
            elif "quota" in error_str or "resource" in error_str or "exhausted" in error_str:
                results["gemini"]["message"] = "Quota excedida"
            elif "response.text" in error_str or "valid `part`" in error_str:
                results["gemini"]["status"] = "warning"
                results["gemini"]["message"] = "API OK mas resposta bloqueada por filtros de segurança"
            else:
                results["gemini"]["message"] = f"Erro: {str(e)[:100]}"
    else:
        results["gemini"]["configured"] = False
        results["gemini"]["status"] = "not_configured"
        results["gemini"]["message"] = "Chave de API não configurada"

    return jsonify(results)


@app.route('/')
@login_required
def home():
    """Home page with form to start new analysis."""
    # Get list of previous analyses
    companies = []
    if OUTPUT_DIR.exists():
        for item in OUTPUT_DIR.iterdir():
            if item.is_dir() and (item / "state.json").exists():
                try:
                    tracker = ProgressTracker(item.name)
                    summary = tracker.get_progress_summary()

                    # Parse timestamp from directory name if versioned (e.g., empresa_20250102_143000)
                    dir_name = item.name
                    version_date = None
                    if '_' in dir_name and len(dir_name.split('_')) >= 3:
                        parts = dir_name.split('_')
                        # Check if last two parts look like timestamp
                        if len(parts[-1]) == 6 and len(parts[-2]) == 8:
                            try:
                                timestamp_str = f"{parts[-2]}_{parts[-1]}"
                                version_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                            except:
                                pass

                    # If no timestamp in folder name, use created_at from state
                    if not version_date and tracker.state.created_at:
                        version_date = tracker.state.created_at

                    companies.append({
                        "name": summary["company_name"],
                        "slug": item.name,
                        "phase": summary["current_phase"],
                        "progress": summary["deliverables"]["progress_percent"],
                        "cost": summary["costs"]["total"],
                        "version_date": version_date,
                    })
                except:
                    pass

    # Sort by company name and then by date (newest first)
    companies.sort(key=lambda x: (x["name"], x["version_date"] or datetime.min), reverse=True)

    # Get active jobs
    running_jobs = []
    for job_id, job_data in active_jobs.items():
        running_jobs.append({
            "job_id": job_id,
            "company_name": job_data.get("company_name", "Unknown"),
            "company_slug": job_data.get("company_slug", ""),
        })

    from jinja2 import Template
    content = Template(HOME_CONTENT).render(companies=companies, running_jobs=running_jobs)

    return render_template_string(
        BASE_TEMPLATE,
        title="Home",
        content=content,
        scripts=HOME_SCRIPTS
    )


@app.route('/start', methods=['POST'])
@login_required
def start_analysis():
    """Start a new analysis job."""
    company_name = request.form.get('company', '').strip()
    context = request.form.get('context', '').strip()
    mode = request.form.get('mode', 'quick')

    if not company_name:
        return jsonify({"error": "Company name is required"}), 400

    # Generate a job ID
    job_id = str(uuid.uuid4())[:8]

    # ALWAYS create new version with timestamp (removed new_version checkbox)
    # This prevents conflicts and keeps all analysis versions separate
    new_version = True

    # Create job entry (company_slug will be updated after ProgressTracker creates timestamped dir)
    active_jobs[job_id] = {
        "company_name": company_name,
        "company_slug": slugify(company_name),  # Temporary, will be updated with timestamp
        "context": context,
        "mode": mode,
        "new_version": new_version,
        "status": "starting",
        "progress_queue": queue.Queue(),
        "started_at": datetime.now(),
    }

    # Start the pipeline in a background thread
    thread = threading.Thread(
        target=run_pipeline,
        args=(job_id, company_name, context, mode, new_version),
        daemon=True
    )
    thread.start()

    # PRG Pattern: Redirect to progress page (GET route)
    return redirect(url_for('progress_page', job_id=job_id, company_name=company_name))


@app.route('/cancel/<job_id>', methods=['POST'])
@login_required
def cancel_job(job_id):
    """Cancel a running analysis job."""
    if job_id not in active_jobs:
        return jsonify({"error": "Job not found"}), 404

    job = active_jobs[job_id]
    company_name = job.get("company_name", "Unknown")

    # Mark job as cancelled
    job["cancelled"] = True
    job["progress_queue"].put({
        "error": True,
        "message": "Análise cancelada pelo usuário",
        "complete": True
    })

    # Remove from active jobs
    del active_jobs[job_id]

    return jsonify({
        "success": True,
        "message": f"Análise de '{company_name}' cancelada com sucesso."
    })


@app.route('/continue/<company_slug>', methods=['POST'])
@login_required
def continue_analysis(company_slug):
    """Continue an incomplete analysis from where it stopped."""
    logger = logging.getLogger(__name__)
    logger.info(f"=== CONTINUE ANALYSIS START for slug: {company_slug} ===")

    output_dir = OUTPUT_DIR / company_slug

    if not output_dir.exists():
        logger.error(f"Directory not found: {output_dir}")
        return redirect(url_for('home'))

    try:
        # Load the existing tracker from the specific directory
        # Use a dummy company name since we'll load the real one from state
        logger.info(f"Loading ProgressTracker from directory: {company_slug}")
        tracker = ProgressTracker(
            company_name="Loading...",  # Temporary, will be loaded from state
            load_from_directory=company_slug  # Load from this specific directory
        )
        company_name = tracker.state.company_name
        context = tracker.state.input_data.context if tracker.state.input_data else ""
        mode = tracker.state.input_data.mode.value if tracker.state.input_data else "quick"
        logger.info(f"Loaded: company_name={company_name}, context={context}, mode={mode}")
    except Exception as e:
        logger.error(f"Failed to load tracker: {e}", exc_info=True)
        return redirect(url_for('home'))

    # Check if this analysis is currently running
    for job_id, job_data in active_jobs.items():
        if job_data.get("company_slug") == company_slug:
            logger.warning(f"Analysis already running: {company_slug}")
            return redirect(url_for('conflict_page', company_slug=company_slug, job_id=job_id, action='continue'))

    # Generate a job ID
    job_id = str(uuid.uuid4())[:8]
    logger.info(f"Generated job_id: {job_id}")

    # Create job entry
    active_jobs[job_id] = {
        "company_name": company_name,
        "company_slug": company_slug,
        "context": context,
        "mode": mode,
        "new_version": False,  # Continue uses existing directory
        "continue_mode": True,  # Flag to indicate this is a continuation
        "status": "continuing",
        "progress_queue": queue.Queue(),
        "started_at": datetime.now(),
    }
    logger.info(f"Created job entry for continuation")

    # Start the pipeline in continuation mode
    logger.info(f"Starting pipeline thread for continuation")
    thread = threading.Thread(
        target=run_pipeline,
        args=(job_id, company_name, context, mode, False, True),  # Added continue_mode parameter
        daemon=True
    )
    thread.start()
    logger.info(f"Thread started, redirecting to progress page")

    # PRG Pattern: Redirect to progress page
    return redirect(url_for('progress_page', job_id=job_id, company_name=company_name))


@app.route('/delete/<company_slug>', methods=['POST'])
@login_required
def delete_analysis(company_slug):
    """Delete an analysis and all its files."""
    import shutil
    logger = logging.getLogger(__name__)

    output_dir = OUTPUT_DIR / company_slug

    if not output_dir.exists():
        logger.warning(f"Delete attempted for non-existent analysis: {company_slug}")
        return redirect(url_for('home'))

    # Check if analysis is currently running
    for job_id, job_data in active_jobs.items():
        if job_data.get("company_slug") == company_slug:
            logger.warning(f"Cannot delete running analysis: {company_slug}")
            content = f"""
            <div style="max-width: 600px; margin: 3rem auto;">
                <div class="card" style="background: #fee; border-left: 4px solid #dc2626;">
                    <h2 style="color: #991b1b; margin: 0 0 1rem 0;">❌ Não é possível excluir</h2>
                    <p style="color: #7f1d1d; margin: 0 0 1rem 0;">
                        A análise <strong>{company_slug}</strong> está em andamento e não pode ser excluída.
                    </p>
                    <p style="color: #7f1d1d; margin: 0 0 1.5rem 0; font-size: 0.9rem;">
                        Cancele a análise primeiro antes de tentar excluir.
                    </p>
                    <a href="/" class="btn" style="background: #2563eb; text-decoration: none; display: inline-block;">
                        ← Voltar para home
                    </a>
                </div>
            </div>
            """
            return render_template_string(BASE_TEMPLATE, title="Erro ao Excluir", content=content, scripts="")

    try:
        # Delete directory and all contents
        shutil.rmtree(output_dir)
        logger.info(f"Successfully deleted analysis: {company_slug}")
    except Exception as e:
        logger.error(f"Error deleting analysis {company_slug}: {e}", exc_info=True)
        content = f"""
        <div style="max-width: 600px; margin: 3rem auto;">
            <div class="card" style="background: #fee; border-left: 4px solid #dc2626;">
                <h2 style="color: #991b1b; margin: 0 0 1rem 0;">❌ Erro ao Excluir</h2>
                <p style="color: #7f1d1d; margin: 0 0 1rem 0;">
                    Ocorreu um erro ao tentar excluir a análise <strong>{company_slug}</strong>.
                </p>
                <p style="color: #7f1d1d; margin: 0 0 1.5rem 0; font-size: 0.9rem; font-family: monospace;">
                    Erro: {str(e)}
                </p>
                <a href="/" class="btn" style="background: #2563eb; text-decoration: none; display: inline-block;">
                    ← Voltar para home
                </a>
            </div>
        </div>
        """
        return render_template_string(BASE_TEMPLATE, title="Erro ao Excluir", content=content, scripts="")

    return redirect(url_for('home'))


@app.route('/progress')
@login_required
def progress_page():
    """Progress page (GET route for PRG pattern)."""
    job_id = request.args.get('job_id')
    company_name = request.args.get('company_name', 'Company')

    if not job_id:
        return redirect(url_for('home'))

    from jinja2 import Template
    content = Template(PROGRESS_CONTENT).render(company_name=company_name)
    scripts = Template(PROGRESS_SCRIPTS).render(job_id=job_id)

    return render_template_string(
        BASE_TEMPLATE,
        title=f"Analisando {company_name}",
        content=content,
        scripts=scripts
    )


@app.route('/conflict')
@login_required
def conflict_page():
    """Conflict page when job is already running (GET route for PRG pattern)."""
    logger = logging.getLogger(__name__)
    company_slug = request.args.get('company_slug')
    job_id = request.args.get('job_id')
    action = request.args.get('action', 'start')  # 'start' only now

    logger.info(f"=== CONFLICT PAGE accessed ===")
    logger.info(f"company_slug={company_slug}, job_id={job_id}, action={action}")
    logger.info(f"Current active_jobs: {list(active_jobs.keys())}")

    if not company_slug or not job_id:
        logger.warning("Missing company_slug or job_id - redirecting to home")
        return redirect(url_for('home'))

    # Get company name from active job or tracker
    company_name = company_slug
    if job_id in active_jobs:
        company_name = active_jobs[job_id].get("company_name", company_slug)
        logger.info(f"Job {job_id} found in active_jobs: company_name={company_name}")
    else:
        # Job might have finished already - redirect to results
        logger.info(f"Job {job_id} NOT in active_jobs - redirecting to results")
        return redirect(url_for('results', company_slug=company_slug))

    action_text = "iniciar nova"
    back_text = "Voltar para home"

    content = f"""
    <div style="max-width: 600px; margin: 3rem auto;">
        <div class="card" style="background: #fffbeb; border-left: 4px solid #f59e0b;">
            <h2 style="color: #92400e; margin: 0 0 1rem 0;">⚠️ Análise em Andamento</h2>
            <p style="color: #78350f; margin: 0 0 1rem 0;">
                Já existe uma análise em andamento para <strong>{company_name}</strong>.
            </p>
            <p style="color: #78350f; margin: 0 0 1.5rem 0; font-size: 0.9rem;">
                Você pode:
            </p>
            <div style="display: flex; gap: 1rem; flex-direction: column;">
                <button onclick="cancelAndRetry('{job_id}', '{company_slug}', '{action}')" class="btn" style="background: #dc2626;">
                    ❌ Cancelar análise atual e {action_text}
                </button>
                <a href="/results/{company_slug}" class="btn btn-secondary" style="text-align: center; text-decoration: none;">
                    👁️ Ver progresso da análise atual
                </a>
                <a href="/" class="btn btn-secondary" style="text-align: center; text-decoration: none;">
                    ← {back_text}
                </a>
            </div>
        </div>
    </div>
    <script>
        function cancelAndRetry(jobId, companySlug, action) {{
            if (!confirm('Tem certeza que deseja cancelar a análise em andamento?')) {{
                return;
            }}
            fetch('/cancel/' + jobId, {{ method: 'POST' }})
                .then(response => response.json())
                .then(data => {{
                    if (data.success) {{
                        // Wait a moment then go back to home
                        setTimeout(() => {{
                            window.location.href = '/';
                        }}, 500);
                    }} else {{
                        alert('Erro ao cancelar: ' + (data.error || 'Erro desconhecido'));
                    }}
                }})
                .catch(err => {{
                    alert('Erro ao cancelar: ' + err);
                }});
        }}
    </script>
    """

    return render_template_string(BASE_TEMPLATE, title="Análise em Andamento", content=content, scripts="")


@app.route('/progress/<job_id>')
@login_required
def progress_stream(job_id):
    """Server-Sent Events stream for progress updates."""
    if job_id not in active_jobs:
        return jsonify({"error": "Job not found"}), 404

    def generate():
        job = active_jobs[job_id]
        q = job["progress_queue"]

        while True:
            try:
                # Wait for progress update
                update = q.get(timeout=30)
                yield f"data: {json.dumps(update)}\n\n"

                if update.get("complete") or update.get("error"):
                    break
            except queue.Empty:
                # Send keepalive
                yield f"data: {json.dumps({'keepalive': True})}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/results/<company_slug>')
def results(company_slug):
    """View results for a company (public - no login required)."""
    output_dir = OUTPUT_DIR / company_slug

    if not output_dir.exists():
        return render_template_string(
            BASE_TEMPLATE,
            title="Não Encontrado",
            content=f"""
            <div class="card" style="text-align: center; padding: 3rem;">
                <h2 style="color: var(--error);">❌ Análise não encontrada</h2>
                <p>O diretório <code>{company_slug}</code> não existe.</p>
                <a href="/" class="btn">Voltar para Home</a>
            </div>
            """,
            scripts=""
        ), 404

    try:
        tracker = ProgressTracker(company_slug)
        summary = tracker.get_progress_summary()
    except Exception as e:
        return render_template_string(
            BASE_TEMPLATE,
            title="Erro",
            content=f"""
            <div class="card" style="text-align: center; padding: 3rem;">
                <h2 style="color: var(--error);">⚠️ Erro ao carregar análise</h2>
                <p>Erro: {str(e)}</p>
                <a href="/" class="btn">Voltar para Home</a>
            </div>
            """,
            scripts=""
        ), 500

    # Get markdown files
    markdown_files = []
    markdown_dir = output_dir / "markdown"
    if markdown_dir.exists():
        for md_file in sorted(markdown_dir.glob("*.md")):
            markdown_files.append({
                "name": md_file.stem.replace("_", " ").title(),
                "filename": md_file.name,
            })

    # Get diagrams
    mermaid_images = []
    mermaid_dir = output_dir / "mermaid_images"
    if mermaid_dir.exists():
        for img in sorted(mermaid_dir.glob("*.png")):
            mermaid_images.append({
                "name": img.stem.replace("_", " ").title(),
                "filename": img.name,
            })

    # Get presentations and documents
    presentations = []
    pres_dir = output_dir / "presentations"
    if pres_dir.exists():
        for pptx in sorted(pres_dir.glob("*.pptx")):
            presentations.append({
                "name": pptx.stem.replace("_", " ").title(),
                "filename": pptx.name,
                "size": f"{pptx.stat().st_size / 1024:.1f} KB"
            })

    documents = []
    docs_dir = output_dir / "documents"
    if docs_dir.exists():
        for docx in sorted(docs_dir.glob("*.docx")):
            documents.append({
                "name": docx.stem.replace("_", " ").title(),
                "filename": docx.name,
                "size": f"{docx.stat().st_size / 1024:.1f} KB"
            })

    content = render_results_page(
        company_name=summary["company_name"],
        company_slug=company_slug,
        total_cost=summary["costs"]["total"],
        markdown_files=markdown_files,
        mermaid_images=mermaid_images,
        presentations=presentations,
        documents=documents,
        summary=summary
    )

    return render_template_string(
        BASE_TEMPLATE,
        title=summary["company_name"],
        content=content,
        scripts=RESULTS_SCRIPTS
    )


def fix_malformed_tables(content: str) -> str:
    """Fix malformed markdown tables with overly long separator rows."""
    import re
    lines = content.split('\n')
    fixed_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip extremely long lines (likely malformed)
        if len(line) > 500:
            i += 1
            continue

        # Check if this looks like a table header row (has multiple | but not a separator)
        if line.count('|') >= 2 and not re.match(r'^\s*\|[\s\-:]+\|', line):
            cols = [c.strip() for c in line.split('|')]
            cols = [c for c in cols if c]
            num_cols = len(cols)

            if num_cols >= 2:
                # Check if next line is a malformed separator (too long)
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if len(next_line) > 200 and '-' in next_line:
                        # Create proper separator
                        separator = '|' + '|'.join([' --- ' for _ in range(num_cols)]) + '|'
                        fixed_lines.append(line)
                        fixed_lines.append(separator)
                        # Add a note that table data was unavailable
                        fixed_lines.append('')
                        fixed_lines.append('*Table data not available in source document.*')
                        fixed_lines.append('')
                        i += 2
                        continue

        fixed_lines.append(line)
        i += 1

    return '\n'.join(fixed_lines)


@app.route('/api/markdown/<company_slug>/<filename>')
def get_markdown(company_slug, filename):
    """Get rendered markdown content (public)."""
    md_path = OUTPUT_DIR / company_slug / "markdown" / filename

    if not md_path.exists():
        return "File not found", 404

    with open(md_path, "r") as f:
        content = f.read()

    # Remove YAML frontmatter if present
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2].strip()

    # Fix malformed tables
    content = fix_malformed_tables(content)

    # Convert markdown to HTML
    html = markdown.markdown(
        content,
        extensions=[
            TableExtension(),
            FencedCodeExtension(),
            TocExtension(),
            'nl2br'
        ]
    )

    return f'<div class="markdown-content">{html}</div>'


@app.route('/files/<company_slug>/<path:filepath>')
def serve_file(company_slug, filepath):
    """Serve static files (images, presentations, documents) - public."""
    directory = OUTPUT_DIR / company_slug
    return send_from_directory(directory, filepath)


@app.route('/download-all-markdown/<company_slug>')
def download_all_markdown(company_slug):
    """Download all markdown files as a ZIP (public)."""
    import zipfile
    import io

    output_dir = OUTPUT_DIR / company_slug / "markdown"

    if not output_dir.exists():
        return "Markdown files not found", 404

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for md_file in sorted(output_dir.glob("*.md")):
            zip_file.write(md_file, arcname=md_file.name)

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'{company_slug}_markdown_docs.zip'
    )


@app.route('/download-all-diagrams/<company_slug>')
def download_all_diagrams(company_slug):
    """Download all diagram images as a ZIP (public)."""
    import zipfile
    import io

    output_dir = OUTPUT_DIR / company_slug / "mermaid_images"

    if not output_dir.exists():
        return "Diagrams not found", 404

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Add PNG images
        for img_file in sorted(output_dir.glob("*.png")):
            zip_file.write(img_file, arcname=img_file.name)
        # Add Mermaid source scripts
        for mmd_file in sorted(output_dir.glob("*.mmd")):
            zip_file.write(mmd_file, arcname=mmd_file.name)

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'{company_slug}_diagrams.zip'
    )


def render_results_page(company_name, company_slug, total_cost, markdown_files, mermaid_images, presentations, documents, summary):
    """Render the results page HTML."""

    # Check analysis completion status
    phases = summary.get('phases', {})
    current_phase = summary.get('current_phase', 'unknown')
    deliverables = summary.get('deliverables', {})

    html = f"""
    <div class="stats-bar">
        <div class="stat-item">
            <div class="stat-value">{len(markdown_files)}</div>
            <div class="stat-label">Documentos MD</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">{len(mermaid_images)}</div>
            <div class="stat-label">Diagramas</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">{len(presentations) + len(documents)}</div>
            <div class="stat-label">PPTX/DOCX</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${total_cost:.4f}</div>
            <div class="stat-label">Custo</div>
        </div>
        <div class="stat-item" style="flex: 2; display: flex; gap: 0.5rem; align-items: center;">
            <form action="/delete/{company_slug}" method="POST" onsubmit="return confirm('⚠️ Tem certeza que deseja excluir esta análise?\\n\\nTodos os arquivos serão permanentemente removidos e esta ação NÃO pode ser desfeita.');" style="flex: 1;">
                <button type="submit" class="btn" style="background: #dc2626; width: 100%; padding: 0.5rem; font-size: 0.75rem;">
                    Excluir
                </button>
            </form>
        </div>
    </div>
    """

    # Show warning if analysis incomplete
    if deliverables.get('progress_percent', 0) < 100:
        # Show error details if available
        error_details_html = ""
        if summary.get('errors'):
            latest_error = summary['errors'][-1]  # Get most recent error
            error_phase = latest_error.get('phase', latest_error.get('deliverable', 'unknown'))
            error_msg = latest_error.get('error', 'Unknown error')
            error_details_html = f"""
            <div style="background: #fee; padding: 0.75rem; border-radius: 6px; margin-top: 0.75rem; border: 1px solid #fcc;">
                <p style="margin: 0; font-size: 0.85rem; color: #dc2626;">
                    <strong>🔴 Erro detectado:</strong> {error_phase}
                </p>
                <p style="margin: 0.5rem 0 0 0; font-size: 0.8rem; color: #991b1b; font-family: monospace;">
                    {error_msg[:200]}{'...' if len(error_msg) > 200 else ''}
                </p>
            </div>
            """

        html += f"""
        <div class="card" style="background: #fffbeb; border-left: 4px solid #f59e0b; margin-bottom: 1rem;">
            <h4 style="color: #92400e; margin: 0 0 0.5rem 0;">⚠️ Análise Incompleta</h4>
            <p style="color: #78350f; margin: 0 0 1rem 0; font-size: 0.9rem;">
                Esta análise está {deliverables.get('progress_percent', 0):.0f}% concluída.
                Fase atual: <strong>{current_phase}</strong>
            </p>
            <p style="color: #78350f; margin: 0 0 1rem 0; font-size: 0.85rem;">
                💡 <strong>Por que parou?</strong> Provável erro de API, perda de conexão, ou reinício do servidor.
            </p>
            {error_details_html}
        </div>
        """

    html += """
    <div class="results-layout">
        <aside class="sidebar">
            <h3>Documentos Estratégicos</h3>
    """

    if markdown_files:
        html += f'<a href="/download-all-markdown/{company_slug}" class="download-btn" download style="margin-bottom: 0.75rem; font-size: 0.85rem;">📦 Baixar Todos os MD</a>\n'
        html += '<ul class="nav-list" id="doc-list">\n'
        for md in markdown_files:
            html += f'<li><a href="#" data-file="{md["filename"]}" class="doc-link">{md["name"]}</a></li>\n'
        html += '</ul>\n'
    else:
        html += '<p style="color: #64748b; font-size: 0.9rem; padding: 0.5rem;">Nenhum documento markdown gerado ainda.</p>\n'

    html += '<h3>Diagramas</h3>\n'
    if mermaid_images:
        html += f'<a href="/download-all-diagrams/{company_slug}" class="download-btn" download style="margin-bottom: 0.75rem; font-size: 0.85rem;">📦 Baixar Todos os Diagramas</a>\n'
        html += '<ul class="nav-list">\n'
        html += '<li><a href="#" id="show-diagrams">👁️ Ver Todos os Diagramas</a></li>\n'
        html += '</ul>\n'
    else:
        html += '<p style="color: #64748b; font-size: 0.9rem; padding: 0.5rem;">Nenhum diagrama gerado ainda.</p>\n'

    html += '<h3>Apresentações</h3>\n'
    if presentations:
        for pres in presentations:
            html += f'<a href="/files/{company_slug}/presentations/{pres["filename"]}" class="download-btn" download>📊 {pres["name"]}<span class="size">{pres["size"]}</span></a>\n'
    else:
        html += '<p style="color: #64748b; font-size: 0.9rem; padding: 0.5rem;">Apresentações serão geradas após os documentos markdown.</p>\n'

    html += '<h3>Documentos</h3>\n'
    if documents:
        for doc in documents:
            html += f'<a href="/files/{company_slug}/documents/{doc["filename"]}" class="download-btn" download>📄 {doc["name"]}<span class="size">{doc["size"]}</span></a>\n'
    else:
        html += '<p style="color: #64748b; font-size: 0.9rem; padding: 0.5rem;">Documentos Word serão gerados após os documentos markdown.</p>\n'

    html += f"""
        </aside>

        <main class="content" id="content">
            <div style="text-align: center; padding: 3rem;">
                <h2>Estratégia de IA para {company_name}</h2>
                <p style="color: var(--text-secondary); max-width: 500px; margin: 1rem auto 2rem;">
                    Selecione um documento na barra lateral para visualizar a análise, ou faça o download das apresentações e relatórios.
                </p>
            </div>
        </main>
    </div>

    <script>
        const companySlug = '{company_slug}';
        const diagramsHtml = `
            <h2>Diagramas de Arquitetura do Sistema</h2>
            <div class="diagrams-grid">
    """

    for img in mermaid_images:
        html += f'<div class="diagram-card"><img src="/files/{company_slug}/mermaid_images/{img["filename"]}" alt="{img["name"]}"><h4>{img["name"]}</h4></div>\n'

    html += """
            </div>
        `;
    </script>
    """

    return html


RESULTS_SCRIPTS = """
<script>
    document.addEventListener('DOMContentLoaded', function() {
        // Document links
        document.querySelectorAll('.doc-link').forEach(link => {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                const filename = this.getAttribute('data-file');

                // Update active state
                document.querySelectorAll('.doc-link').forEach(l => l.classList.remove('active'));
                this.classList.add('active');

                // Load content
                fetch('/api/markdown/' + companySlug + '/' + filename)
                    .then(response => response.text())
                    .then(html => {
                        document.getElementById('content').innerHTML = html;
                    })
                    .catch(err => {
                        document.getElementById('content').innerHTML = '<p>Error loading content.</p>';
                    });
            });
        });

        // Diagrams link
        document.getElementById('show-diagrams').addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelectorAll('.doc-link').forEach(l => l.classList.remove('active'));
            document.getElementById('content').innerHTML = diagramsHtml;
        });

        // Load first document by default
        const firstDoc = document.querySelector('.doc-link');
        if (firstDoc) firstDoc.click();
    });
</script>
"""


# =============================================================================
# Pipeline Execution
# =============================================================================

def run_pipeline(job_id: str, company_name: str, context: str, mode: str, new_version: bool = False, continue_mode: bool = False):
    """Run the full pipeline in a background thread."""
    logger = logging.getLogger(__name__)
    logger.info(f"=== RUN_PIPELINE START ===")
    logger.info(f"job_id={job_id}, company_name={company_name}, mode={mode}, new_version={new_version}, continue_mode={continue_mode}")

    job = active_jobs.get(job_id)
    if not job:
        logger.error(f"Job {job_id} not found in active_jobs - was it cancelled?")
        return  # Job was cancelled before starting

    q = job["progress_queue"]
    logger.info(f"Got job and queue for {job_id}")

    def check_cancelled():
        """Check if job was cancelled."""
        if job_id not in active_jobs or active_jobs[job_id].get("cancelled", False):
            logger.info(f"Job {job_id} was cancelled")
            raise Exception("Análise cancelada pelo usuário")

    try:
        logger.info("Importing dependencies...")
        # Import here to avoid circular imports
        from strategy_factory.models import CompanyInput, ResearchMode
        from strategy_factory.progress_tracker import ProgressTracker
        from strategy_factory.research.orchestrator import ResearchOrchestrator
        from strategy_factory.synthesis.orchestrator import SynthesisOrchestrator
        from strategy_factory.generation.orchestrator import GenerationOrchestrator

        research_mode = ResearchMode.QUICK if mode == "quick" else ResearchMode.COMPREHENSIVE
        logger.info(f"Research mode: {research_mode}")

        logger.info("Creating CompanyInput...")
        company_input = CompanyInput(
            name=company_name,
            context=context,
            mode=research_mode,
        )

        logger.info(f"Initializing ProgressTracker (create_new_version={new_version}, continue_mode={continue_mode})...")

        # If continuing, use the existing directory from active_jobs
        # Otherwise create new with or without timestamp
        if continue_mode and job_id in active_jobs:
            existing_slug = active_jobs[job_id].get("company_slug")
            logger.info(f"Continue mode: loading from directory {existing_slug}")
            tracker = ProgressTracker(
                company_name=company_name,
                company_input=company_input,
                load_from_directory=existing_slug
            )
        else:
            tracker = ProgressTracker(company_name, company_input, create_new_version=new_version)

        logger.info(f"ProgressTracker initialized: output_dir={tracker.output_dir}")

        # Update company_slug in active_jobs to match actual directory name
        # This is critical when new_version=True creates a timestamped directory
        if job_id in active_jobs:
            actual_slug = tracker.output_dir.name
            active_jobs[job_id]["company_slug"] = actual_slug
            logger.info(f"Updated company_slug in active_jobs: {actual_slug}")

        # Phase 1: Research
        q.put({
            "phase": "research",
            "message": "Starting research...",
            "status": "Gathering company intelligence",
            "progress": 0,
            "detail": "Initializing"
        })

        def research_callback(message: str, progress: float):
            q.put({
                "phase": "research",
                "message": f"Research: {message}",
                "status": "Researching",
                "progress": int(progress * 100),
                "detail": message
            })

        # Determine if we need to run research
        logger = logging.getLogger(__name__)
        research_completed = tracker.state.phases["research"].status == DeliverableStatus.COMPLETED

        # Only run new research if NOT in continue mode OR research not completed
        if continue_mode and research_completed:
            logger.info(f"CONTINUE MODE: Skipping research (already completed)")
            # Load existing research from cache
            research_output = tracker.load_research_output()
            if not research_output:
                raise Exception("Cannot continue: research cache not found")

            q.put({
                "phase": "research",
                "message": "Using cached research data (already completed)",
                "status": "Cached",
                "progress": 100,
                "detail": "Skipping research - using existing data"
            })
        else:
            logger.info(f"Starting new research phase (continue_mode={continue_mode}, new_version={new_version})")
            tracker.start_phase("research")

            research_orchestrator = ResearchOrchestrator(
                mode=research_mode,
                cache_dir=Path(tracker.output_dir),
                progress_callback=research_callback,
            )

            research_output = research_orchestrator.research(company_input)
            tracker.save_research_output(research_output)
            research_orchestrator.save_research_cache(Path(tracker.output_dir))
            tracker.complete_phase("research", f"Completed research with {len(research_orchestrator.results)} queries")

        # Validate research output exists (critical dependency for all phases)
        if not research_output:
            raise Exception("Cache de dados da fase inicial está ausente ou corrompido. Não é possível continuar.")

        q.put({
            "phase": "research",
            "completed": True,
            "message": "Research complete"
        })

        # Check if cancelled before continuing
        check_cancelled()

        # Phase 2: Synthesis
        q.put({
            "phase": "synthesis",
            "message": "Starting synthesis...",
            "status": "Generating deliverables",
            "progress": 0,
            "detail": "Initializing"
        })

        # Check which deliverables are pending
        pending_deliverables = tracker.get_pending_deliverables()
        markdown_deliverables = [
            d_id for d_id, config in DELIVERABLES.items()
            if config.get("format") == "markdown"
        ]
        pending_markdown = [d for d in pending_deliverables if d in markdown_deliverables]

        synthesis_orchestrator = None  # Initialize to None
        synthesis_output = None
        file_paths = {}

        if pending_markdown:
            # Only run synthesis for pending deliverables
            tracker.start_phase("synthesis")

            def synthesis_callback(message: str, progress: float):
                q.put({
                    "phase": "synthesis",
                    "message": f"Synthesis: {message}",
                    "status": "Synthesizing",
                    "progress": int(progress * 100),
                    "detail": message
                })

            synthesis_orchestrator = SynthesisOrchestrator(
                output_dir=OUTPUT_DIR,
                progress_callback=synthesis_callback,
            )

            # Only synthesize pending deliverables
            synthesis_output = synthesis_orchestrator.synthesize(
                company_input,
                research_output,
                deliverables=pending_markdown
            )
            # Use the full directory name with timestamp
            company_slug_with_timestamp = tracker.output_dir.name
            file_paths = synthesis_orchestrator.save_deliverables(company_slug_with_timestamp)
        else:
            # All synthesis already completed
            q.put({
                "phase": "synthesis",
                "message": "All markdown deliverables already generated",
                "status": "Cached",
                "progress": 100,
                "detail": "Skipping synthesis - all deliverables complete"
            })

            # Load existing synthesis from files
            from strategy_factory.models import SynthesisOutput
            synthesis_output = SynthesisOutput(
                company_name=company_input.name,
                synthesis_timestamp=datetime.now(),
                deliverables={},
                total_cost=0.0,
            )

            # Ensure phase is marked as completed if all deliverables are done
            if tracker.state.phases["synthesis"].status != DeliverableStatus.COMPLETED:
                tracker.complete_phase("synthesis", "All markdown deliverables already generated")

        for d_id, path in file_paths.items():
            tracker.complete_deliverable(d_id, path)

        # Check for synthesis errors (only if we ran synthesis)
        if synthesis_orchestrator and synthesis_orchestrator.errors:
            error_msg = f"{len(synthesis_orchestrator.errors)} deliverable(s) failed: "
            error_details = "; ".join([f"{e['deliverable']}: {e['error'][:100]}" for e in synthesis_orchestrator.errors[:3]])
            tracker.fail_phase("synthesis", error_msg + error_details)

            # Log each individual error
            for error in synthesis_orchestrator.errors:
                logger = logging.getLogger(__name__)
                logger.error(f"Synthesis error for {error['deliverable']}: {error['error']}")

            raise Exception(error_msg + error_details)

        # Only mark synthesis complete if we actually ran it
        if pending_markdown:
            tracker.complete_phase("synthesis", f"Generated {len(file_paths)} deliverables")

        q.put({
            "phase": "synthesis",
            "completed": True,
            "message": "Synthesis complete"
        })

        # Check if cancelled before continuing
        check_cancelled()

        # Phase 3: Generation
        # Check which generation deliverables are pending
        generation_deliverables = [
            d_id for d_id, config in DELIVERABLES.items()
            if config.get("format") in ["pptx", "docx"]
        ]
        pending_generation = [d for d in tracker.get_pending_deliverables() if d in generation_deliverables]

        if not pending_generation:
            # All generation already completed
            q.put({
                "phase": "generation",
                "message": "All presentations and documents already generated",
                "status": "Cached",
                "progress": 100,
                "detail": "Skipping generation - all files complete"
            })

            # Ensure phase is marked as completed if all deliverables are done
            if tracker.state.phases["generation"].status != DeliverableStatus.COMPLETED:
                tracker.complete_phase("generation", "All documents already generated")
        else:
            q.put({
                "phase": "generation",
                "message": "Starting document generation...",
                "status": "Creating presentations and reports",
                "progress": 0,
                "detail": "Initializing"
            })

            tracker.start_phase("generation")

            def generation_callback(message: str, progress: float):
                q.put({
                    "phase": "generation",
                    "message": f"Generation: {message}",
                    "status": "Generating",
                    "progress": int(progress * 100),
                    "detail": message
                })

            generation_orchestrator = GenerationOrchestrator(
                output_dir=OUTPUT_DIR,
                progress_callback=generation_callback,
            )

            # Use the full directory name with timestamp
            company_slug_with_timestamp = tracker.output_dir.name
            result = generation_orchestrator.generate_all(
                company_slug=company_slug_with_timestamp,
                company_input=company_input,
                research=research_output,
                synthesis=synthesis_output,
            )

            # Update tracker for generated files
            for deliverable in result.deliverables:
                d_name = deliverable["name"]
                d_path = deliverable["path"]
                # Find the deliverable ID from the name
                for d_id, config in DELIVERABLES.items():
                    if config.get("name") == d_name:
                        tracker.complete_deliverable(d_id, d_path)
                        break

            tracker.complete_phase("generation", f"Generated {len(result.deliverables)} documents")

        q.put({
            "phase": "generation",
            "completed": True,
            "message": "Generation complete"
        })

        # Complete
        # Use the actual directory name (with timestamp) not just the base slug
        actual_company_slug = tracker.output_dir.name
        logger.info(f"=== PIPELINE COMPLETE for job {job_id} ===")
        logger.info(f"Company slug with timestamp: {actual_company_slug}")
        logger.info(f"Output directory: {tracker.output_dir}")

        q.put({
            "complete": True,
            "company_slug": actual_company_slug,
            "message": "Analysis complete!"
        })

        # Remove from active jobs immediately when complete
        if job_id in active_jobs:
            del active_jobs[job_id]
            logger.info(f"Job {job_id} completed successfully - removed from active_jobs")
            logger.info(f"Active jobs remaining: {list(active_jobs.keys())}")
        else:
            logger.warning(f"Job {job_id} was not in active_jobs when trying to remove it")

    except Exception as e:
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"=== PIPELINE EXCEPTION for job {job_id} ===")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error("Traceback:")
        traceback.print_exc()

        # Determine which phase we were in
        # PRIORITY 1: Use tracker's current_phase (most accurate)
        current_phase = "unknown"
        if 'tracker' in locals() and tracker.state.current_phase:
            current_phase = tracker.state.current_phase
            logger.info(f"Phase determined from tracker: {current_phase}")
        else:
            # PRIORITY 2: Infer from error message (fallback)
            if "research" in str(e).lower() or "perplexity" in str(e).lower():
                current_phase = "research"
            elif "synthesis" in str(e).lower() or "gemini" in str(e).lower():
                current_phase = "synthesis"
            elif "generation" in str(e).lower() or "pptx" in str(e).lower() or "docx" in str(e).lower():
                current_phase = "generation"
            logger.info(f"Phase inferred from error message: {current_phase}")

        # Get detailed error information
        error_details = get_error_details(e, current_phase)
        logger.info(f"Error details generated: title={error_details['title']}")

        # Save error to tracker if tracker was created
        if 'tracker' in locals():
            try:
                # Mark the phase as failed in tracker
                logger.info(f"Marking phase {current_phase} as failed in tracker")
                tracker.fail_phase(current_phase, error_details["message"])

                # Log the full error for debugging
                logger.error(f"Pipeline failed in {current_phase} phase: {error_details['message']}")
                logger.error(f"Technical details: {error_details['technical']}")
            except Exception as track_err:
                logger.error(f"Warning: Could not save error to tracker: {track_err}")
                print(f"Warning: Could not save error to tracker: {track_err}")
        else:
            logger.warning("Tracker not initialized - cannot save error to state")

        logger.info("Sending error to progress queue...")
        q.put({
            "error": str(e),
            "error_title": error_details["title"],
            "error_message": error_details["message"],
            "error_solution": error_details["solution"],
            "error_technical": error_details["technical"],
            "error_phase": current_phase,
            "complete": True  # Mark as complete so SSE stream ends
        })
        logger.info("Error sent to queue")

        # Clean up job immediately on error (don't wait 1 hour)
        # This allows the user to retry immediately
        logger.info(f"Checking if job {job_id} is in active_jobs for cleanup...")
        if job_id in active_jobs:
            logger.info(f"Deleting job {job_id} from active_jobs")
            del active_jobs[job_id]
            logger.info(f"Cleaned up failed job {job_id} immediately - job removed from active_jobs")
            logger.info(f"Active jobs remaining: {list(active_jobs.keys())}")
        else:
            logger.warning(f"Job {job_id} was NOT in active_jobs - already cleaned up?")


# =============================================================================
# Main
# =============================================================================

def main():
    """Run the web application."""
    import argparse
    import socket

    parser = argparse.ArgumentParser(description="PASTANA Web App")
    parser.add_argument("--port", "-p", type=int, default=8888, help="Port to run on (default: 8888)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    # Check for API keys
    missing_keys = []
    if not os.getenv("PERPLEXITY_API_KEY"):
        missing_keys.append("PERPLEXITY_API_KEY")
    if not os.getenv("GEMINI_API_KEY"):
        missing_keys.append("GEMINI_API_KEY")

    if missing_keys:
        print("Warning: Missing API keys:", ", ".join(missing_keys))
        print("Set these in your .env file for full functionality.\n")

    import webbrowser

    # Find an available port if default is in use
    port = args.port
    def is_port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0

    if is_port_in_use(port):
        print(f"Port {port} is in use, trying alternatives...")
        for alt_port in [8889, 8890, 9000, 9001]:
            if not is_port_in_use(alt_port):
                port = alt_port
                break
        else:
            print("Error: Could not find an available port. Try specifying one with --port")
            return 1

    url = f"http://localhost:{port}"

    print("\n" + "=" * 50)
    print("PASTANA Web App")
    print("=" * 50)
    print(f"Server running at: {url}")
    print("Press Ctrl+C to stop\n")

    if not args.no_browser:
        webbrowser.open(url)

    try:
        app.run(host=args.host, port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\nServer stopped.")
        return 0


if __name__ == "__main__":
    main()


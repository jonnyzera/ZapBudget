from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from supabase import create_client
import os
import stripe
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from app.routes import budgets

# Carrega as variáveis de ambiente do ficheiro .env
load_dotenv()

app = FastAPI()

# Configuração de Stripe (Chaves devem estar no .env e no painel da Vercel)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Configuração de CORS atualizada para o seu novo domínio oficial
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://zapbudget.com.br", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro do endpoint de PDF (Referencia o budgets.py com fpdf2 para Vercel)
app.include_router(budgets.router, prefix="/api/v1/pdf", tags=["PDF"])

# Caminhos de diretórios para servir o Frontend e arquivos estáticos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
ROOT_DIR = os.path.dirname(BASE_DIR)

# Monta a pasta de estáticos se ela existir
if os.path.exists(TEMPLATES_DIR):
    app.mount("/templates", StaticFiles(directory=TEMPLATES_DIR), name="templates")

# Credenciais Supabase (Service Role é necessária para gerenciar perfis)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Erro: Variáveis SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não encontradas.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Modelo de Dados para validação de entrada
class Orcamento(BaseModel):
    user_id: str
    vendor_name: str
    client_name: str
    servicos: str
    valor: str
    prazo: str = None
    pagamento: str = None
    validade: str = None 

# --- ROTAS DE PAGAMENTO (STRIPE WEBHOOK) ---

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """
    Escuta eventos do Stripe para ativar ou desativar o Premium no Supabase automaticamente.
    Configure este endpoint no Stripe como: https://zapbudget.com.br/webhook/stripe
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro no Webhook: {str(e)}")

    # Evento: Pagamento concluído no checkout
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        # Recupera o ID do usuário enviado pelo frontend via client_reference_id
        user_id = session.get('client_reference_id')
        
        if user_id:
            # Atualiza o perfil para Premium e armazena o ID do cliente Stripe para futuras cobranças
            supabase.table("profiles").update({
                "is_premium": True,
                "stripe_customer_id": session.get('customer')
            }).eq("id", user_id).execute()

    # Evento: Assinatura cancelada, expirada ou falha no pagamento
    elif event['type'] in ['customer.subscription.deleted', 'customer.subscription.updated']:
        subscription = event['data']['object']
        # Se o status da assinatura não for mais 'active', removemos o acesso Pro
        if subscription.get('status') != 'active':
            res = supabase.table("profiles").select("id").eq("stripe_customer_id", subscription['customer']).execute()
            if res.data:
                supabase.table("profiles").update({"is_premium": False}).eq("id", res.data[0]['id']).execute()

    return {"status": "success"}

# --- ROTAS PWA E NAVEGAÇÃO ---

@app.get("/")
async def serve_home():
    """Serve o site principal"""
    site_path = os.path.join(TEMPLATES_DIR, "site.html")
    return FileResponse(site_path) if os.path.exists(site_path) else {"message": "ZapBudget API Ativa"}

@app.get("/manifest.json")
async def serve_manifest():
    """Serve o manifesto para o PWA ser instalável no zapbudget.com.br"""
    return FileResponse(os.path.join(ROOT_DIR, "manifest.json"))

@app.get("/service-worker.js")
async def serve_sw():
    """Serve o service worker para cache offline"""
    return FileResponse(os.path.join(ROOT_DIR, "service-worker.js"))

@app.get("/favicon.ico")
async def favicon():
    """Evita erro 404 de favicon"""
    favicon_path = os.path.join(TEMPLATES_DIR, "img", "favicon (3).png")
    return FileResponse(favicon_path) if os.path.exists(favicon_path) else HTTPException(status_code=404)

# --- ROTAS DA API DE ORÇAMENTOS ---

@app.post("/orcamentos")
async def salvar_orcamento(dados: Orcamento):
    """Cria orçamentos validando o trial ou assinatura premium do usuário"""
    try:
        # Verifica o status do perfil no Supabase
        res_profile = supabase.table("profiles").select("*").eq("id", dados.user_id).execute()
        
        if not res_profile.data:
            # Primeiro uso: Cria perfil com 7 dias de trial
            new_profile = {
                "id": dados.user_id,
                "trial_start": datetime.now(timezone.utc).isoformat(),
                "is_premium": False
            }
            supabase.table("profiles").insert(new_profile).execute()
            profile = new_profile
        else:
            profile = res_profile.data[0]

        # Bloqueia criação se o trial expirou e não é premium
        if not profile.get("is_premium", False):
            start_str = profile["trial_start"].replace("Z", "+00:00")
            trial_start = datetime.fromisoformat(start_str)
            if datetime.now(timezone.utc) > (trial_start + timedelta(days=7)):
                raise HTTPException(
                    status_code=402, 
                    detail="Seu período de teste terminou. Assine o Pro para continuar!"
                )

        # Salva o orçamento e retorna o ID para o link dinâmico
        payload = dados.model_dump(exclude_none=True)
        res_budget = supabase.table("orçamentos").insert(payload).execute()
        
        if not res_budget.data:
            raise HTTPException(status_code=500, detail="Falha ao salvar orçamento")
            
        return {"id": res_budget.data[0]['id']}
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Erro Interno: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno no servidor")

@app.get("/orcamentos/{id}")
async def buscar_orcamento(id: str):
    """Busca dados de um orçamento para visualização pública"""
    try:
        res = supabase.table("orçamentos").select("*").eq("id", id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Orçamento não encontrado")
        return res.data[0]
    except Exception:
        raise HTTPException(status_code=404, detail="Erro ao buscar orçamento")